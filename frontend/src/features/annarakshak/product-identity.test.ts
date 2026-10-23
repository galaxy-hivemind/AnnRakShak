import { describe, it, expect } from 'vitest';
import {
  formatProductDisplayName,
  cleanRawNameString,
  titleCaseName,
} from './product-identity';

describe('Product Identity Service (Frontend)', () => {
  describe('formatProductDisplayName', () => {
    it('uses explicit displayName property when available', () => {
      const result = formatProductDisplayName({
        name: 'Milk',
        displayName: 'Amul Taaza Toned Milk',
      });
      expect(result).toBe('Amul Taaza Toned Milk');
    });

    it('identifies signature product lines', () => {
      expect(
        formatProductDisplayName({
          name: 'Taaza 1L',
          brand: 'Amul',
          category: 'Dairy & Eggs',
        })
      ).toBe('Amul Taaza Toned Milk');

      expect(
        formatProductDisplayName({
          name: 'Parle Products',
          brand: 'Parle',
          category: 'Pantry Staples',
        })
      ).toBe('Parle-G Original Glucose Biscuits');

      expect(
        formatProductDisplayName({
          name: 'Maggi',
          brand: 'Nestle',
          category: 'Pantry Staples',
        })
      ).toBe('Maggi 2-Minute Masala Noodles');

      expect(
        formatProductDisplayName({
          name: 'Fortune 1L',
          brand: 'Fortune',
          category: 'Pantry Staples',
        })
      ).toBe('Fortune Sunflower Oil');
    });

    it('protects regional and traditional food specialties', () => {
      expect(
        formatProductDisplayName({
          name: 'Poha Thick',
          brand: '',
          category: 'Grains & Cereals',
        })
      ).toBe('Poha');

      expect(
        formatProductDisplayName({
          name: 'Methi Khakhra',
          brand: '',
          category: 'Pantry Staples',
        })
      ).toBe('Khakhra');

      expect(
        formatProductDisplayName({
          name: 'Sattu Pure',
          brand: 'Organic',
          category: 'Grains & Cereals',
        })
      ).toBe('Organic Sattu');
    });

    it('deduplicates brand repetition', () => {
      const result = formatProductDisplayName({
        name: 'Amul Milk',
        brand: 'Amul',
        category: 'Dairy & Eggs',
      });
      expect(result).toBe('Amul Milk');
    });
  });

  describe('cleanRawNameString', () => {
    it('removes duplicate consecutive words', () => {
      expect(cleanRawNameString('Amul Amul Milk')).toBe('Amul Milk');
    });

    it('strips batch and manufacturing noise', () => {
      const raw = 'Tata Salt 1kg B.No. 402 MFG 10/25';
      const cleaned = cleanRawNameString(raw);
      expect(cleaned).not.toContain('MFG');
      expect(cleaned).not.toContain('B.No');
      expect(cleaned).toContain('Tata Salt');
    });
  });

  describe('titleCaseName', () => {
    it('preserves uppercase acronyms', () => {
      const titled = titleCaseName('amul uht toned milk');
      expect(titled).toContain('UHT');
      expect(titled).toContain('Amul');
    });
  });
});
