"""校级统计只读模型；跨模块只消费正式返宿与目录领域出口。"""
import base64
import hashlib
import json
from collections import defaultdict
from datetime import timedelta

from app.core.clock import business_iso, service_date_of
from app.core.config import get_settings
from app.core.errors import ApiError
from app.modules.directory import service as directory
from app.modules.reservation import service as reservations
from app.modules.returns import service as returns


def invalid(message):
    return ApiError(422, 'VALIDATION_FAILED', message, {})


def window(clock, period):
    current = service_date_of(clock.now())
    end = current - timedelta(days=1)
    if period == 'DAY':
        start = end
    elif period == 'WEEK':
        start = end - timedelta(days=end.weekday())
    elif period == 'MONTH':
        start = end.replace(day=1)
    else:
        raise invalid('统计周期必须是 DAY、WEEK 或 MONTH。')
    return current, start, end


def options(conn):
    return directory.filter_catalog(conn)


def validate_filters(catalog, filters):
    allowed = {
        'college_org_id': {r['org_id'] for r in catalog['colleges']},
        'park_org_id': {r['org_id'] for r in catalog['parks']},
        'building_id': {r['building_id'] for r in catalog['buildings']},
        'grade': set(catalog['grades']),
        'education_level': set(catalog['education_levels']),
    }
    for key, values in allowed.items():
        if filters.get(key) and filters[key] not in values:
            raise invalid(f'未知筛选条件：{key}。')
    if filters.get('park_org_id') and filters.get('building_id'):
        building = next(r for r in catalog['buildings'] if r['building_id'] == filters['building_id'])
        if building['park_org_id'] != filters['park_org_id']:
            raise invalid('所选楼栋不属于所选宿舍区。')


def matching(meta, filters, buildings):
    building = meta.get('night_building_id')
    values = {'education_level': meta.get('education_level'), 'college_org_id': meta['college_org_id'], 'grade': meta['night_grade'],
              'building_id': building, 'park_org_id': buildings.get(building, {}).get('park_org_id')}
    return all(not value or values.get(key) == value for key, value in filters.items())


def collect(db, context, clock, period, filters, dataset):
    current, start, end = window(clock, period)
    conn = db.connection()
    catalog = options(conn)
    validate_filters(catalog, filters)
    buildings = {r['building_id']: r for r in catalog['buildings']}
    allowed = set(context.scope.get('student_ids') or [])
    if dataset == 'RESERVED':
        if period != 'DAY':
            raise invalid('今日预约名单仅适用于日统计。')
        rows = reservations.list_reservations(db, clock, scope={'student_ids': sorted(allowed)}, service_date=current)
        keys = {(r.student_id, current) for r in rows if r.status != 'CANCELLED'}
    elif dataset in ('RETURNED', 'REPEATED'):
        if dataset == 'REPEATED' and period == 'DAY':
            raise invalid('多次晚归名单仅适用于周统计或月统计。')
        keys = returns.returned_keys(conn, start, end)
    else:
        raise invalid('未知名单类型。')
    # 按每个事实发生业务夜取住宿归属，不能用当前宿舍替代历史。
    dimensions = {night: directory.statistic_students(conn, night) for night in {night for _, night in keys}}
    grouped = defaultdict(list)
    for sid, night in sorted(keys):
        meta = dimensions[night].get(sid)
        if sid in allowed and meta and matching(meta, filters, buildings):
            grouped[sid].append((night, meta))
    return grouped, catalog, (current, start, end)


def overview(db, context, clock, period, filters):
    grouped, _, (current, start, end) = collect(db, context, clock, period, filters, 'RETURNED')
    minimum = get_settings().report_repeat_min_nights
    today_count = 0
    if period == 'DAY':
        reserved, _, _ = collect(db, context, clock, period, filters, 'RESERVED')
        today_count = len(reserved)
    return {'period': period, 'current_service_date': current.isoformat(),
            'date_from': start.isoformat(), 'date_to': end.isoformat(), 'generated_at': business_iso(clock.now()),
            'yesterday_returned_people': len(grouped) if period == 'DAY' else 0,
            'today_reserved_people': today_count, 'returned_people': len(grouped),
            'returned_nights': sum(len(rows) for rows in grouped.values()),
            'repeated_people': sum(len(rows) >= minimum for rows in grouped.values()),
            'repeat_min_nights': minimum}


def decode_cursor(cursor, fingerprint):
    if not cursor:
        return 0
    try:
        if len(cursor) > 2048:
            raise ValueError()
        data = json.loads(base64.b64decode(cursor.encode('ascii'), altchars=b'-_', validate=True))
        offset = data['offset']
        if data['query'] != fingerprint or type(offset) is not int or offset < 0:
            raise ValueError()
        return offset
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise invalid('游标无效或筛选条件已变化，请重新查询。') from None


def students(db, context, clock, period, filters, dataset, cursor, limit):
    grouped, catalog, dates = collect(db, context, clock, period, filters, dataset)
    minimum = get_settings().report_repeat_min_nights
    if dataset == 'REPEATED':
        grouped = {sid: rows for sid, rows in grouped.items() if len(rows) >= minimum}
    fingerprint = hashlib.sha256(json.dumps([context.user_id, context.scope, period, dataset, filters,
        [d.isoformat() for d in dates], minimum], sort_keys=True).encode()).hexdigest()
    offset = decode_cursor(cursor, fingerprint)
    colleges = {r['org_id']: r['name'] for r in catalog['colleges']}
    parks = {r['org_id']: r['name'] for r in catalog['parks']}
    buildings = {r['building_id']: r for r in catalog['buildings']}
    # 只有名单接口读取姓名；汇总与筛选选项均不返回学生身份。
    labels = {}
    for night in {rows[-1][0] for rows in grouped.values()}:
        labels[night] = directory.return_labels(db.connection(), night)
    ordered = sorted(grouped, key=lambda sid: (-len(grouped[sid]),
        labels[grouped[sid][-1][0]].get(sid, {}).get('school_id', sid), sid))
    items = []
    for sid in ordered[offset:offset + limit]:
        rows = grouped[sid]
        night, meta = rows[-1]
        label = labels[night].get(sid, {})
        building = meta.get('night_building_id') or ''
        park = buildings.get(building, {}).get('park_org_id') or ''
        college = meta['college_org_id']
        items.append({'student_id': sid, 'school_id': label.get('school_id', sid),
            'display_name': label.get('display_name', sid), 'college_org_id': college,
            'college_name': colleges.get(college, college), 'grade': meta['night_grade'],
            'building_id': building, 'building_name': buildings.get(building, {}).get('name', '未同步'),
            'park_org_id': park, 'park_name': parks.get(park, '未同步'),
            'return_nights': 0 if dataset == 'RESERVED' else len(rows),
            'service_dates': [r[0].isoformat() for r in rows]})
    next_cursor = None
    if offset + limit < len(ordered):
        next_cursor = base64.urlsafe_b64encode(json.dumps({'offset': offset + limit, 'query': fingerprint}).encode()).decode()
    return {'items': items, 'next_cursor': next_cursor, 'total_matches': len(ordered)}
