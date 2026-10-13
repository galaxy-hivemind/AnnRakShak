import { describe,it,expect } from 'vitest';
import { mockService } from './mock';
import type { ProductInput } from './types';
describe('mock adapter integrity',()=>{
 it('requires an exact date for month-only confirmation',async()=>{const scans=await mockService.getScanHistory();const month=scans.find(s=>s.reason==='Month/year-only date');if(!month)throw new Error('Missing month-only seed');await expect(mockService.confirmDate(month.id,'c1')).rejects.toThrow('no exact date');const after=await mockService.getScanById(month.id);expect(after.reviewStatus).toBe('Needs Review');expect(after.productId).toBeUndefined();});
 it('successful analysis does not confirm a date, and confirmation is idempotent',async()=>{const scan=await mockService.startScan();expect(scan.reviewStatus).toBe('Needs Review');expect(scan.productId).toBeUndefined();const p=await mockService.confirmDate(scan.id,'c1');expect(p.verified).toBe(true);const again=await mockService.confirmDate(scan.id,'c1');expect(again.id).toBe(p.id);await mockService.deleteProduct(p.id);const retained=await mockService.getScanById(scan.id);expect(retained.id).toBe(scan.id);expect(retained.productId).toBeUndefined();});
 it('validates corrections before changing existing inventory',async()=>{const scan=await mockService.startScan();const product=await mockService.confirmDate(scan.id,'c1');const bad:ProductInput={...product,date:'2026-02-31'};await expect(mockService.correctScan(scan.id,bad)).rejects.toThrow('valid full calendar date');expect((await mockService.getProductById(product.id)).date).toBe(product.date);});
});
