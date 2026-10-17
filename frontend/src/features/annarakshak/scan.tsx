import { useState, useRef, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Camera, ScanLine, Upload, RotateCcw, X, Check, LoaderCircle, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { service } from '@/services/api';
import type { ScanRecord } from '@/services/types';
import { PageIntro, PanelHead, Footer, Empty } from './common';
import { AnalysisPanel } from './scan-details';

type CaptureState = 'Ready' | 'Streaming' | 'Analyzing' | 'Analysis Failed' | 'Complete';

export function Scan() {
  const [state, setState] = useState<CaptureState>('Ready');
  const [capturedImage, setCapturedImage] = useState('');
  const [scan, setScan] = useState<ScanRecord>();
  const [error, setError] = useState('');
  const [cameraError, setCameraError] = useState('');

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const sequence = useRef(0);
  const qc = useQueryClient();

  function stopCamera() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }

  useEffect(() => {
    return () => {
      sequence.current++;
      stopCamera();
    };
  }, []);

  useEffect(() => {
    if (state === 'Streaming' && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => {});
    }
  }, [state]);

  async function startCamera() {
    setCameraError('');
    setError('');
    setScan(undefined);
    setCapturedImage('');

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCameraError('Camera access is not supported in this browser environment. Please upload an image instead.');
      setState('Ready');
      return;
    }

    try {
      stopCamera();
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      streamRef.current = stream;
      setState('Streaming');
    } catch (err: unknown) {
      stopCamera();
      setState('Ready');
      if (err instanceof DOMException) {
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
          setCameraError('Camera access was denied. Please allow camera permissions in your browser or upload an image.');
        } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
          setCameraError('No camera found on this device. Please connect a camera or upload a packaging photo.');
        } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
          setCameraError('Camera is already in use by another application. Please close other camera apps and retry.');
        } else {
          setCameraError(`Camera error: ${err.message}`);
        }
      } else {
        setCameraError('Failed to access camera. Please check browser permissions or use image upload.');
      }
    }
  }

  function captureFrame(): string | null {
    if (!videoRef.current) return null;
    const video = videoRef.current;
    const width = video.videoWidth || 640;
    const height = video.videoHeight || 480;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, width, height);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
    stopCamera();
    return dataUrl;
  }

  const isSubmitting = useRef(false);

  async function executeScan(imageData: string) {
    if (isSubmitting.current) return;
    isSubmitting.current = true;
    const run = ++sequence.current;
    setScan(undefined);
    setError('');
    setCameraError('');
    setCapturedImage(imageData);
    setState('Analyzing');

    try {
      const result = await service.startScan(imageData);
      if (run !== sequence.current) return;
      setScan(result);
      if (result.analysisStatus === 'Failed') {
        setState('Analysis Failed');
        setError(result.reason || 'Analysis could not extract readable date evidence. Retry analysis or edit details manually.');
      } else {
        setState('Complete');
      }
      await qc.invalidateQueries();
    } catch (err: unknown) {
      if (run !== sequence.current) return;
      setState('Analysis Failed');
      setError(err instanceof Error ? err.message : 'Analysis failed. Please check backend connection and retry.');
    } finally {
      isSubmitting.current = false;
    }
  }

  function handleCapture() {
    if (busy || isSubmitting.current) return;
    const frame = captureFrame();
    if (!frame) {
      setError('Could not capture frame from video stream. Please ensure camera is active and try again.');
      return;
    }
    void executeScan(frame);
  }

  function handleRetake() {
    setCapturedImage('');
    setScan(undefined);
    setError('');
    setCameraError('');
    void startCamera();
  }

  function handleCancel() {
    sequence.current++;
    stopCamera();
    setCapturedImage('');
    setScan(undefined);
    setError('');
    setCameraError('');
    setState('Ready');
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setError('Please choose a valid image file (JPEG, PNG, WebP).');
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      setError('Please choose an image smaller than 15 MB.');
      return;
    }
    stopCamera();
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        void executeScan(reader.result);
      }
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  }

  const busy = state === 'Analyzing';

  return (
    <div className="page">
      <PageIntro
        title="Scan food packaging"
        description="Capture packaging. Verify printed dates. Add confirmed items to your inventory."
      />

      <div className="demo-strip">
        <Camera size={18} className="shrink-0" />
        <span>
          <strong>Live packaging scanner.</strong> Hold the front label and printed date steadily in frame, or upload a clear packaging photo.
        </span>
      </div>

      <div className="scan-grid">
        <section className="panel">
          <PanelHead title="Product capture" subtitle="Front label and printed date" />

          <div className="capture-indicator" aria-live="polite">
            {busy && <LoaderCircle size={13} className="animate-spin" />}
            {state === 'Streaming'
              ? 'Camera active · Live preview'
              : state === 'Analyzing'
              ? 'Analyzing with OCR & Gemini…'
              : state === 'Complete'
              ? 'Capture complete · Evidence extracted'
              : state === 'Analysis Failed'
              ? 'Analysis failed · Check photo or retry'
              : 'Ready to scan'}
          </div>

          {cameraError && (
            <div className="form-error mx-5 mb-3" role="alert">
              {cameraError}
            </div>
          )}

          <div className="camera-area">
            {state === 'Streaming' ? (
              <div className="relative w-full h-full flex items-center justify-center bg-black overflow-hidden">
                <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover" />
                <div className="absolute inset-0 pointer-events-none flex items-center justify-center p-6">
                  <div className="w-full max-w-[280px] h-[260px] border-2 border-white/70 border-dashed rounded-lg flex flex-col justify-between p-3 text-white text-[11px] font-medium shadow-[0_0_0_9999px_rgba(0,0,0,0.4)]">
                    <span className="bg-black/60 backdrop-blur-sm px-2 py-0.5 rounded self-start">
                      Align packaging & date label
                    </span>
                    <span className="bg-black/60 backdrop-blur-sm px-2 py-0.5 rounded self-center text-[10px] text-white/90">
                      Hold steady for clearest capture
                    </span>
                  </div>
                </div>
              </div>
            ) : capturedImage || scan ? (
              <img
                src={capturedImage || scan?.image}
                alt="Captured packaging preview"
                width={400}
                height={380}
              />
            ) : (
              <>
                <div className="camera-frame">
                  <Camera size={42} strokeWidth={1} />
                </div>
                <p className="text-xs text-muted-foreground mt-5">Camera ready</p>
                <p className="text-[11px] text-muted-foreground mt-1">
                  Start camera to capture packaging or upload a photo
                </p>
              </>
            )}

            {busy && (
              <div className="absolute inset-0 bg-overlay flex flex-col gap-3 items-center justify-center text-primary-foreground">
                <LoaderCircle className="animate-spin" size={32} />
                <span className="text-sm font-medium">Extracting packaging details and dates…</span>
                <span className="text-xs opacity-75">Running Apple Vision OCR & Gemini AI</span>
              </div>
            )}
          </div>

          <div className="scan-actions">
            {state === 'Streaming' ? (
              <>
                <Button onClick={handleCapture} disabled={busy}>
                  <ScanLine />
                  Capture & Scan
                </Button>
                <Button variant="outline" onClick={handleCancel}>
                  <X />
                  Cancel
                </Button>
              </>
            ) : state === 'Analyzing' ? (
              <Button variant="ghost" onClick={handleCancel} disabled={busy}>
                <X />
                Cancel
              </Button>
            ) : capturedImage || scan ? (
              <>
                <Button onClick={() => void startCamera()}>
                  <Camera />
                  Start Camera
                </Button>
                <Button variant="outline" onClick={handleRetake}>
                  <RotateCcw />
                  Retake Photo
                </Button>
                <Button variant="outline" onClick={() => input.current?.click()}>
                  <Upload />
                  Upload Image
                </Button>
                <Button variant="ghost" onClick={handleCancel}>
                  <X />
                  Clear
                </Button>
              </>
            ) : (
              <>
                <Button onClick={() => void startCamera()}>
                  <Camera />
                  Start Camera
                </Button>
                <Button variant="outline" onClick={() => input.current?.click()}>
                  <Upload />
                  Upload Image
                </Button>
              </>
            )}

            <input
              ref={input}
              type="file"
              accept="image/*"
              className="hidden"
              aria-label="Upload packaging image"
              onChange={handleFile}
            />
          </div>
        </section>

        <section className="panel">
          <PanelHead title="Product analysis" subtitle="Original evidence first. Your confirmation next." />
          {error && (
            <div className="form-error mx-5 mb-4" role="alert">
              {error}
            </div>
          )}
          {scan ? (
            <AnalysisPanel
              key={scan.id}
              scan={scan}
              onChange={(s) => {
                setScan(s);
                setState(s.analysisStatus === 'Failed' ? 'Analysis Failed' : 'Complete');
                setError('');
              }}
            />
          ) : busy ? (
            <div className="loading">
              <LoaderCircle className="animate-spin" />
              Analyzing packaging with OCR and Gemini…
            </div>
          ) : (
            <Empty
              title="Ready when you are"
              message="Product details and printed-date evidence will appear here after capturing a photo."
            />
          )}
          {scan?.reviewStatus === 'Confirmed' && (
            <div className="scan-actions">
              <Button asChild>
                <Link to="/inventory" search={{ q: scan.name }}>
                  <Check />
                  View in inventory
                  <ArrowRight />
                </Link>
              </Button>
            </div>
          )}
        </section>
      </div>

      <Footer />
    </div>
  );
}
