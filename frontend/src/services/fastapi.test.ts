import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { FastApiFoodSafetyService, getApiBaseUrl, toFrontendCategory, toBackendCategory, toFrontendDateType, toBackendDateType, parseId } from './fastapi';

describe('FastApiFoodSafetyService Adapter', () => {
  let service: FastApiFoodSafetyService;

  beforeEach(() => {
    service = new FastApiFoodSafetyService('http://127.0.0.1:8000');
    vi.restoreAllMocks();
  });

  it('converts categories accurately between frontend and backend', () => {
    expect(toFrontendCategory('Dairy')).toBe('Dairy & Eggs');
    expect(toFrontendCategory('Bakery')).toBe('Grains & Cereals');
    expect(toFrontendCategory('Beverage')).toBe('Beverages');
    expect(toFrontendCategory('Snacks')).toBe('Snacks');
    expect(toFrontendCategory('Produce')).toBe('Fresh Produce');
    expect(toFrontendCategory('Unknown')).toBe('Pantry Staples');

    expect(toBackendCategory('Dairy & Eggs')).toBe('Dairy');
    expect(toBackendCategory('Grains & Cereals')).toBe('Grains');
    expect(toBackendCategory('Beverages')).toBe('Beverage');
    expect(toBackendCategory('Fresh Produce')).toBe('Produce');
    expect(toBackendCategory('Pantry Staples')).toBe('Pantry');
  });

  it('converts date types accurately', () => {
    expect(toFrontendDateType('expiry')).toBe('Expiry');
    expect(toFrontendDateType('use_by')).toBe('Use By');
    expect(toFrontendDateType('best_before')).toBe('Best Before');
    expect(toFrontendDateType('manufacturing')).toBe('Manufacturing');
    expect(toFrontendDateType('packed_on')).toBe('Packed On');

    expect(toBackendDateType('Expiry')).toBe('expiry');
    expect(toBackendDateType('Use By')).toBe('use_by');
    expect(toBackendDateType('Best Before')).toBe('best_before');
    expect(toBackendDateType('Manufacturing')).toBe('manufacturing');
    expect(toBackendDateType('Packed On')).toBe('packed_on');
  });

  it('parses numeric product IDs from string prefixes', () => {
    expect(parseId('PR-12')).toBe(12);
    expect(parseId('12')).toBe(12);
    expect(parseId('SC-5')).toBe(5);
    expect(() => parseId('invalid')).toThrow();
  });

  it('fetches and maps products list correctly', async () => {
    const mockProducts = [
      {
        id: 1,
        product_name: 'Amul Taaza Milk',
        brand: 'Amul',
        food_category: 'Dairy',
        date_type: 'expiry',
        date_text: 'EXP 20/10/2026',
        normalized_date: '2026-10-20',
        date_status: 'confirmed',
        current_status: 'expiring_soon',
        date_source: 'printed',
        analysis_status: 'success',
        image_path: null,
        notes: 'Door shelf',
        created_at: '2026-10-12T00:00:00Z',
        updated_at: '2026-10-12T00:00:00Z',
        date_candidates: [],
      },
    ];

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => mockProducts,
    } as Response);

    const products = await service.getProducts();
    expect(products.length).toBe(1);
    expect(products[0].id).toBe('PR-1');
    expect(products[0].name).toBe('Amul Taaza Milk');
    expect(products[0].category).toBe('Dairy & Eggs');
    expect(products[0].verified).toBe(true);
    expect(products[0].dateType).toBe('Expiry');
  });

  it('propagates meaningful errors when API request fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Product with ID 999 not found.' }),
    } as Response);

    await expect(service.getProductById('PR-999')).rejects.toThrow('Product with ID 999 not found.');
  });

  it('posts real captured image to /api/scans and returns mapped ScanRecord', async () => {
    const mockScanResponse = {
      id: 10,
      timestamp: '2026-10-13T12:00:00Z',
      image_path: 'captures/scan_10.jpg',
      product_name: 'Organic Milk',
      brand: 'Horizon',
      food_category: 'Dairy',
      analysis_status: 'success',
      needs_review: true,
      review_reason: 'Confirm printed expiry',
      selected_expiry_date: null,
      error_message: null,
      raw_json: null,
      date_candidates: [
        {
          id: 1,
          product_id: null,
          scan_id: 10,
          raw_text: 'EXP 25/10/2026',
          date_type: 'expiry',
          normalized_date: '2026-10-25',
          confidence: 0.95,
          evidence: 'Cap print',
          created_at: '2026-10-13T12:00:00Z',
        },
      ],
    };

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => mockScanResponse,
    } as Response);

    const scan = await service.startScan('data:image/jpeg;base64,/9j/4AAQSkZJRg==');
    expect(fetchSpy).toHaveBeenCalledWith('http://127.0.0.1:8000/api/scans', expect.objectContaining({
      method: 'POST',
      body: expect.any(FormData),
    }));
    expect(scan.id).toBe('SC-10');
    expect(scan.name).toBe('Organic Milk');
    expect(scan.category).toBe('Dairy & Eggs');
    expect(scan.reviewStatus).toBe('Needs Review');
    expect(scan.image).toBe('http://127.0.0.1:8000/api/scans/10/image');
    expect(scan.candidates.length).toBe(1);
    expect(scan.candidates[0].printedText).toBe('EXP 25/10/2026');
  });

  it('throws meaningful error when image upload fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'Uploaded image is empty (0 bytes).' }),
    } as Response);

    await expect(service.startScan('data:image/jpeg;base64,')).rejects.toThrow('Uploaded image is empty (0 bytes).');
  });

  describe('Vercel Multi-Service URL & Binding Resolution', () => {
    const originalEnv = process.env.FASTAPI_URL;

    afterEach(() => {
      if (originalEnv !== undefined) {
        process.env.FASTAPI_URL = originalEnv;
      } else {
        delete process.env.FASTAPI_URL;
      }
    });

    it('resolves internal binding URL from process.env.FASTAPI_URL', () => {
      process.env.FASTAPI_URL = 'http://app.internal:8080/';
      expect(getApiBaseUrl()).toBe('http://app.internal:8080');

      const boundService = new FastApiFoodSafetyService();
      expect(boundService.baseUrl).toBe('http://app.internal:8080');
    });

    it('uses relative path when running in production browser on Vercel', () => {
      delete process.env.FASTAPI_URL;
      const originalLocation = window.location;
      // @ts-expect-error test mock
      delete window.location;
      // @ts-expect-error test mock
      window.location = { hostname: 'annarakshak.vercel.app' };

      try {
        expect(getApiBaseUrl()).toBe('');
        const vService = new FastApiFoodSafetyService();
        expect(vService.baseUrl).toBe('');
      } finally {
        window.location = originalLocation;
      }
    });

    it('makes relative requests when baseUrl is empty string in production', async () => {
      const vService = new FastApiFoodSafetyService('');
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: 'ok', database: 'connected', total_products: 5, version: '1.0.0' }),
      } as Response);

      await vService.getHealth();
      expect(fetchSpy).toHaveBeenCalledWith('/api/health', expect.any(Object));
    });
  });

  describe('confirmDate multi-candidate handling', () => {
    it('confirms both manufacturing and expiry dates accurately and links scanId', async () => {
      const mockScan = {
        id: 42,
        timestamp: '2026-10-17T00:00:00Z',
        image_path: 'captures/test.jpg',
        product_name: 'Cereal Box',
        brand: 'Kelloggs',
        food_category: 'Grains',
        analysis_status: 'success',
        needs_review: false,
        review_reason: null,
        selected_expiry_date: '2027-08-15',
        error_message: null,
        raw_json: null,
        date_candidates: [
          {
            id: 1,
            raw_text: 'MFG 15/08/2026',
            date_type: 'manufacturing',
            normalized_date: '2026-08-15',
            confidence: 0.95,
            evidence: 'Printed on top',
            created_at: '2026-10-17T00:00:00Z',
          },
          {
            id: 2,
            raw_text: 'EXP 15/08/2027',
            date_type: 'expiry',
            normalized_date: '2027-08-15',
            confidence: 0.98,
            evidence: 'Printed on bottom',
            created_at: '2026-10-17T00:00:00Z',
          },
        ],
      };

      const mockCreatedProduct = {
        id: 99,
        product_name: 'Cereal Box',
        brand: 'Kelloggs',
        food_category: 'Grains',
        date_type: 'expiry',
        date_text: '2027-08-15',
        normalized_date: '2027-08-15',
        date_status: 'confirmed',
        current_status: 'upcoming',
        date_source: 'user_confirmed',
        notes: 'MFG: 2026-08-15 (MFG 15/08/2026) [Verified] | EXP: 2027-08-15 (EXP 15/08/2027) [Verified]',
        created_at: '2026-10-17T00:00:00Z',
        updated_at: '2026-10-17T00:00:00Z',
        date_candidates: [],
      };

      const fetchSpy = vi.spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce({
          ok: true,
          json: async () => mockScan,
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: async () => mockCreatedProduct,
        } as Response);

      const product = await service.confirmDate('SC-42', ['1', '2']);

      expect(fetchSpy).toHaveBeenNthCalledWith(
        2,
        'http://127.0.0.1:8000/api/products',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            product_name: 'Cereal Box',
            brand: 'Kelloggs',
            food_category: 'Grains',
            date_type: 'expiry',
            normalized_date: '2027-08-15',
            date_status: 'confirmed',
            date_source: 'user_confirmed',
            notes: 'MFG: 2026-08-15 (MFG 15/08/2026) [Verified] | EXP: 2027-08-15 (EXP 15/08/2027) [Verified]',
            force: true,
            scan_id: 42,
          }),
        })
      );
      expect(product.dateType).toBe('Expiry');
      expect(product.date).toBe('2027-08-15');
      expect(product.verified).toBe(true);
    });

    it('confirms single manufacturing date without converting it to expiry', async () => {
      const mockScan = {
        id: 50,
        timestamp: '2026-10-17T00:00:00Z',
        image_path: 'captures/test2.jpg',
        product_name: 'Fresh Cheese',
        brand: 'Dairy Co',
        food_category: 'Dairy',
        analysis_status: 'success',
        needs_review: true,
        review_reason: 'Only MFG date printed',
        selected_expiry_date: null,
        error_message: null,
        raw_json: null,
        date_candidates: [
          {
            id: 10,
            raw_text: 'MFG 01/10/2026',
            date_type: 'manufacturing',
            normalized_date: '2026-10-01',
            confidence: 0.95,
            evidence: 'Printed on lid',
            created_at: '2026-10-17T00:00:00Z',
          },
        ],
      };

      const mockCreatedProduct = {
        id: 101,
        product_name: 'Fresh Cheese',
        brand: 'Dairy Co',
        food_category: 'Dairy',
        date_type: 'manufacturing',
        date_text: '2026-10-01',
        normalized_date: '2026-10-01',
        date_status: 'confirmed',
        current_status: 'manufactured',
        date_source: 'user_confirmed',
        notes: 'Manufacturing: 2026-10-01 (MFG 01/10/2026) [Verified]',
        created_at: '2026-10-17T00:00:00Z',
        updated_at: '2026-10-17T00:00:00Z',
        date_candidates: [],
      };

      const fetchSpy = vi.spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce({
          ok: true,
          json: async () => mockScan,
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: async () => mockCreatedProduct,
        } as Response);

      const product = await service.confirmDate('SC-50', '10');

      expect(fetchSpy).toHaveBeenNthCalledWith(
        2,
        'http://127.0.0.1:8000/api/products',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            product_name: 'Fresh Cheese',
            brand: 'Dairy Co',
            food_category: 'Dairy',
            date_type: 'manufacturing',
            normalized_date: '2026-10-01',
            date_status: 'confirmed',
            date_source: 'user_confirmed',
            notes: 'Manufacturing: 2026-10-01 (MFG 01/10/2026) [Verified]',
            force: true,
            scan_id: 50,
          }),
        })
      );
      // Crucial: dateType is Manufacturing, NEVER converted to Expiry!
      expect(product.dateType).toBe('Manufacturing');
      expect(product.date).toBe('2026-10-01');
    });

    it('submits supplementary image with overrides to /api/scans/{id}/supplementary and maps supplementary_images', async () => {
      const mockBackendScan = {
        id: 50,
        product_name: 'Consolidated Water',
        brand: 'Aquafina',
        food_category: 'Beverage',
        quantity: '1 L',
        needs_review: true,
        image_path: 'uploads/scans/50.jpg',
        supplementary_images: ['uploads/scans/50_supp_1.jpg'],
        date_candidates: [
          {
            id: 1,
            raw_text: 'EXP 10/2027',
            date_type: 'expiry',
            normalized_date: '2027-10-15',
            confidence: 0.95,
          },
        ],
        created_at: '2026-10-17T00:00:00Z',
      };

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        json: async () => mockBackendScan,
      } as Response);

      const result = await service.addSupplementaryImage('SC-50', 'data:image/jpeg;base64,abc123mock', {
        name: 'User Edited Name',
        brand: 'Aquafina',
        category: 'Beverages',
        quantity: '1 L',
      });

      expect(fetchSpy).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/api/scans/50/supplementary',
        expect.objectContaining({
          method: 'POST',
          body: expect.any(FormData),
        })
      );

      const calledBody = fetchSpy.mock.calls[0][1]?.body as FormData;
      expect(calledBody.get('product_name')).toBe('User Edited Name');
      expect(calledBody.get('brand')).toBe('Aquafina');
      expect(calledBody.get('food_category')).toBe('Beverages');
      expect(calledBody.get('quantity')).toBe('1 L');

      expect(result.id).toBe('SC-50');
      expect(result.supplementaryImages).toEqual(['http://127.0.0.1:8000/api/scans/50/image?index=1']);
      expect(result.name).toBe('Consolidated Water');
    });
  });
});

