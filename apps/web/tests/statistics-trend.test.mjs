import test from 'node:test'
import assert from 'node:assert/strict'
import { recentTrend } from '../src/features/campus/statisticsTrend.ts'
const days = Array.from({length:14},(_,i)=>({service_date:`2026-11-${String(i+1).padStart(2,'0')}`,nights:i<7?1:2}))
test('two complete windows compare their actual night totals',()=>assert.deepEqual(recentTrend(days),{prior:7,recent:14,delta:7,percent:100}))
test('short or missing-night windows do not imply a trend',()=>{assert.equal(recentTrend(days.slice(1)),null);assert.equal(recentTrend(days.map((d,i)=>i===5?{...d,service_date:'2026-10-01'}:d)),null)})
test('a zero baseline never produces an infinite percentage',()=>assert.equal(recentTrend(days.map((d,i)=>({...d,nights:i<7?0:2}))).percent,null))

test('server range fills zero-return nights without changing window length',()=>assert.deepEqual(recentTrend([days[0],days[13]],{date_from:'2026-11-01',date_to:'2026-11-14'}),{prior:1,recent:2,delta:1,percent:100}))
