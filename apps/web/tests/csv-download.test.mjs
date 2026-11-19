import test from 'node:test'
import assert from 'node:assert/strict'
import { readCsvDownload } from '../src/shared/api/csvDownload.ts'

test('CSV download preserves UTF-8 BOM and Chinese bytes for Excel', async () => {
  const bytes = new TextEncoder().encode('\ufeff片区,晚归人数\r\n东一区,6\r\n')
  const response = new Response(bytes, { headers: { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': 'attachment; filename="statistics.csv"' } })
  const file = await readCsvDownload(response)
  assert.equal(file.fileName, 'statistics.csv')
  assert.deepEqual(new Uint8Array(await file.blob.arrayBuffer()), bytes)
  assert.deepEqual([...new Uint8Array(await file.blob.arrayBuffer()).slice(0, 3)], [239, 187, 191])
})
