import { describe, it, expect } from 'vitest';
import { productStatus, daysFromToday, isExactDate } from './dates';
import type { DateType } from './types';
describe('date integrity',()=>{
 const status=(date:string,dateType:DateType='Expiry',verified=true)=>productStatus({date,dateType,verified},7,'2026-10-11');
 it('classifies confirmed expiry by local calendar days',()=>{expect(status('2026-10-10')).toBe('Expired');expect(status('2026-10-11')).toBe('Expires Today');expect(status('2026-10-18')).toBe('Expiring Soon');expect(status('2026-10-19')).toBe('Upcoming');expect(status('2026-10-10','Use By')).toBe('Expired');});
 it('keeps best before distinct',()=>{expect(status('2026-10-10','Best Before')).toBe('Best Before Passed');expect(status('2026-10-11','Best Before')).toBe('Best Before Today');expect(status('2026-10-18','Best Before')).toBe('Best Before Soon');expect(status('2026-10-19','Best Before')).toBe('Best Before Future');});
 it('never classifies production dates as expiry',()=>{expect(status('2020-01-01','Manufacturing')).toBe('Manufactured');expect(status('2020-01-01','Packed On')).toBe('Packed');});
 it('does not verify incomplete or unconfirmed dates',()=>{expect(status('2026-10','Expiry')).toBe('Needs Review');expect(status('2020-01-01','Expiry',false)).toBe('Needs Review');expect(status('')).toBe('Unknown');});
 it('rejects invalid dates and handles leap years',()=>{expect(isExactDate('2026-02-29')).toBe(false);expect(isExactDate('2024-02-29')).toBe(true);expect(isExactDate('2026-13-01')).toBe(false);expect(isExactDate('2026-04-31')).toBe(false);});
 it('counts days through daylight saving and year boundaries',()=>{expect(daysFromToday('2026-11-02','2026-10-31')).toBe(2);expect(daysFromToday('2027-01-01','2026-12-31')).toBe(1);});
});
