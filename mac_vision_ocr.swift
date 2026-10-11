import Foundation
import Vision
import AppKit

// Apple Vision Text Recognition CLI
// Usage:
//   mac_vision_ocr <image_path>
//   mac_vision_ocr --stdin (reads image paths from stdin, prints JSON per line)

struct TextResult: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

func processImage(path: String) -> [TextResult] {
    let url = URL(fileURLWithPath: path)
    guard let image = NSImage(contentsOf: url),
          let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        return []
    }

    var results: [TextResult] = []
    let request = VNRecognizeTextRequest { req, err in
        guard let observations = req.results as? [VNRecognizedTextObservation] else { return }
        for obs in observations {
            guard let candidate = obs.topCandidates(1).first else { continue }
            let bb = obs.boundingBox
            results.append(TextResult(
                text: candidate.string,
                confidence: candidate.confidence,
                x: Double(bb.origin.x),
                y: Double(bb.origin.y),
                width: Double(bb.size.width),
                height: Double(bb.size.height)
            ))
        }
    }
    request.recognitionLevel = .fast
    request.usesLanguageCorrection = false

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
    } catch {
        return []
    }
    return results
}

let args = CommandLine.arguments

if args.count > 1 && args[1] == "--stdin" {
    let encoder = JSONEncoder()
    while let line = readLine() {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == "EXIT" { break }
        if trimmed.isEmpty { continue }
        let res = processImage(path: trimmed)
        if let data = try? encoder.encode(res), let json = String(data: data, encoding: .utf8) {
            print(json)
            fflush(stdout)
        } else {
            print("[]")
            fflush(stdout)
        }
    }
} else if args.count > 1 {
    let res = processImage(path: args[1])
    let encoder = JSONEncoder()
    if let data = try? encoder.encode(res), let json = String(data: data, encoding: .utf8) {
        print(json)
    } else {
        print("[]")
    }
} else {
    fputs("Usage: mac_vision_ocr <image_path> or mac_vision_ocr --stdin\n", stderr)
    exit(1)
}
