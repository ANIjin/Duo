import Foundation
import Network
import UIKit
import AVFoundation
import VideoToolbox

enum DuoMessageType: UInt8 {
    case hello = 1, config = 2, frame = 3, input = 4
    case ping = 5, pong = 6, bye = 7, keyframeRequest = 8
}

enum DuoClientError: LocalizedError {
    case invalidFrame
    case versionMismatch(peer: UInt8, local: UInt8)

    var errorDescription: String? {
        switch self {
        case .invalidFrame: return "The host sent an invalid protocol frame."
        case let .versionMismatch(peer, local):
            return "Protocol mismatch: host \(peer), iPad \(local). Update the older side."
        }
    }
}

struct DuoFrame {
    let type: DuoMessageType
    let flags: UInt8
    let payload: Data

    func encoded() -> Data {
        var body = Data([type.rawValue, flags])
        body.append(payload)
        var length = UInt32(body.count).bigEndian
        return Data(bytes: &length, count: 4) + body
    }
}

final class DuoFrameParser {
    private var buffer = Data()

    func append(_ data: Data) throws -> [DuoFrame] {
        buffer.append(data)
        var frames: [DuoFrame] = []
        while buffer.count >= 4 {
            let length = (UInt32(buffer[0]) << 24)
                | (UInt32(buffer[1]) << 16)
                | (UInt32(buffer[2]) << 8)
                | UInt32(buffer[3])
            guard length >= 2, length <= 64 * 1024 * 1024 else {
                throw DuoClientError.invalidFrame
            }
            let total = 4 + Int(length)
            guard buffer.count >= total else { break }
            let type = DuoMessageType(rawValue: buffer[4])
            guard let type else { throw DuoClientError.invalidFrame }
            frames.append(DuoFrame(type: type, flags: buffer[5],
                                   payload: buffer.subdata(in: 6..<total)))
            buffer.removeSubrange(0..<total)
        }
        return frames
    }
}

final class DuoClient: NSObject {
    static let protocolVersion: UInt8 = 1
    private var listener: NWListener?
    private var connection: NWConnection?
    private let parser = DuoFrameParser()
    private(set) var status = "Waiting for PC"
    var onImage: ((UIImage) -> Void)?
    var onSampleBuffer: ((CMSampleBuffer) -> Void)?
    var onStatus: ((String) -> Void)?
    private var h264Format: CMVideoFormatDescription?
    private var codec: DuoCodec = .jpeg

    private enum DuoCodec {
        case jpeg, h264
    }

    func start(port: UInt16) throws {
        guard let endpoint = NWEndpoint.Port(rawValue: port) else { throw DuoClientError.invalidFrame }
        let listener = try NWListener(using: .tcp, on: endpoint)
        listener.newConnectionHandler = { [weak self] connection in self?.accept(connection) }
        listener.stateUpdateHandler = { [weak self] state in
            if case .failed(let error) = state { self?.setStatus(error.localizedDescription) }
        }
        listener.start(queue: .main)
        self.listener = listener
    }

    func stop() {
        listener?.cancel()
        connection?.cancel()
        listener = nil
        connection = nil
        setStatus("Waiting for PC")
    }

    private func accept(_ connection: NWConnection) {
        self.connection?.cancel()
        self.connection = connection
        connection.start(queue: .main)
        setStatus("Connected")
        sendHello()
        receive()
    }

    private func sendHello() {
        let pixels = UIScreen.main.nativeBounds.size
        let widthPixels = max(pixels.width, pixels.height)
        let heightPixels = min(pixels.width, pixels.height)
        var payload = Data([DuoClient.protocolVersion])
        var width = UInt16(widthPixels).bigEndian
        var height = UInt16(heightPixels).bigEndian
        var fps = UInt16(60).bigEndian
        var scale = Float(UIScreen.main.nativeScale).bitPattern.bigEndian
        payload.append(Data(bytes: &width, count: 2))
        payload.append(Data(bytes: &height, count: 2))
        payload.append(Data(bytes: &fps, count: 2))
        payload.append(Data(bytes: &scale, count: 4))
        payload.append(2)
        payload.append(contentsOf: [1, 2])
        send(DuoFrame(type: .hello, flags: 0, payload: payload))
    }

    private func receive() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) {
            [weak self] data, _, isComplete, error in
            guard let self else { return }
            if isComplete || error != nil {
                self.setStatus("Waiting for PC")
                self.receive()
                return
            }
            do {
                if let data {
                    for frame in try self.parser.append(data) {
                        self.handle(frame)
                    }
                }
                self.receive()
            } catch {
                self.setStatus(error.localizedDescription)
                self.connection?.cancel()
            }
        }
    }

    private func decodeH264(_ annexB: Data, timestampNs: UInt64) {
        let nalUnits = splitAnnexB(annexB)
        var sps: Data?
        var pps: Data?
        for nal in nalUnits {
            guard let type = nal.first.map({ $0 & 0x1F }) else { continue }
            if type == 7 { sps = nal }
            if type == 8 { pps = nal }
        }
        if h264Format == nil, let sps, let pps {
            var description: CMVideoFormatDescription?
            let status = sps.withUnsafeBytes { spsBytes in
                pps.withUnsafeBytes { ppsBytes in
                    let pointers = [
                        spsBytes.bindMemory(to: UInt8.self).baseAddress!,
                        ppsBytes.bindMemory(to: UInt8.self).baseAddress!,
                    ]
                    let sizes = [sps.count, pps.count]
                    return CMVideoFormatDescriptionCreateFromH264ParameterSets(
                        allocator: kCFAllocatorDefault,
                        parameterSetCount: 2,
                        parameterSetPointers: pointers,
                        parameterSetSizes: sizes,
                        nalUnitHeaderLength: 4,
                        formatDescriptionOut: &description
                    )
                }
            }
            guard status == noErr, let description else { return }
            h264Format = description
        }
        guard let format = h264Format else { return }
        var avcc = Data()
        for nal in nalUnits {
            guard let type = nal.first.map({ $0 & 0x1F }), type != 7, type != 8 else { continue }
            var length = UInt32(nal.count).bigEndian
            avcc.append(Data(bytes: &length, count: 4))
            avcc.append(nal)
        }
        guard !avcc.isEmpty else { return }
        var block: CMBlockBuffer?
        let blockStatus = CMBlockBufferCreateWithMemoryBlock(
            allocator: kCFAllocatorDefault,
            memoryBlock: nil,
            blockLength: avcc.count,
            blockAllocator: nil,
            customBlockSource: nil,
            offsetToData: 0,
            dataLength: avcc.count,
            flags: 0,
            blockBufferOut: &block
        )
        guard blockStatus == kCMBlockBufferNoErr, let block else { return }
        let copyStatus = avcc.withUnsafeBytes { bytes -> OSStatus in
            guard let baseAddress = bytes.baseAddress else {
                return kCMBlockBufferBadPointerParameter
            }
            return CMBlockBufferReplaceDataBytes(
                with: baseAddress,
                blockBuffer: block,
                offsetIntoDestination: 0,
                dataLength: avcc.count
            )
        }
        guard copyStatus == kCMBlockBufferNoErr else { return }
        var timing = CMSampleTimingInfo(
            duration: CMTime(value: 1, timescale: 60),
            presentationTimeStamp: CMTime(value: CMTimeValue(timestampNs), timescale: 1_000_000_000),
            decodeTimeStamp: .invalid
        )
        var sample: CMSampleBuffer?
        let sampleStatus = CMSampleBufferCreateReady(
            allocator: kCFAllocatorDefault,
            dataBuffer: block,
            formatDescription: format,
            sampleCount: 1,
            sampleTimingEntryCount: 1,
            sampleTimingArray: &timing,
            sampleSizeEntryCount: 1,
            sampleSizeArray: [avcc.count],
            sampleBufferOut: &sample
        )
        if sampleStatus == noErr, let sample {
            DispatchQueue.main.async { self.onSampleBuffer?(sample) }
        }
    }

    private func splitAnnexB(_ data: Data) -> [Data] {
        let bytes = [UInt8](data)
        var starts: [Int] = []
        var index = 0
        while index + 3 < bytes.count {
            if bytes[index] == 0 && bytes[index + 1] == 0 &&
                ((bytes[index + 2] == 1) ||
                 (bytes[index + 2] == 0 && bytes[index + 3] == 1)) {
                starts.append(index)
                index += bytes[index + 2] == 1 ? 3 : 4
            } else {
                index += 1
            }
        }
        return starts.enumerated().compactMap { position, start in
            let prefix = bytes[start + 2] == 1 ? 3 : 4
            let end = position + 1 < starts.count ? starts[position + 1] : bytes.count
            guard end > start + prefix else { return nil }
            return Data(bytes[(start + prefix)..<end])
        }
    }

    private func handle(_ frame: DuoFrame) {
        switch frame.type {
        case .frame:
            guard frame.payload.count > 8 else { return }
            let timestamp = frame.payload.prefix(8).reduce(UInt64(0)) {
                ($0 << 8) | UInt64($1)
            }
            let data = Data(frame.payload.dropFirst(8))
            if self.codec == .h264 {
                decodeH264(data, timestampNs: timestamp)
            } else if let image = UIImage(data: data) {
                DispatchQueue.main.async { self.onImage?(image) }
            }
        case .config:
            guard frame.payload.count >= 11 else { return }
            let codec = frame.payload[0]
            if codec == 1 {
                self.codec = .jpeg
                setStatus("Streaming JPEG")
            } else if codec == 2 {
                self.codec = .h264
                self.h264Format = nil
                setStatus("Streaming H.264")
            }

        case .ping:
            send(DuoFrame(type: .pong, flags: 0, payload: frame.payload))
        case .bye:
            setStatus("Waiting for PC")
        default:
            break
        }
    }

    private func send(_ frame: DuoFrame) {
        connection?.send(content: frame.encoded(), completion: .contentProcessed { [weak self] error in
            if let error { self?.setStatus(error.localizedDescription) }
        })
    }

    func sendInput(contactID: UInt16, phase: UInt8, x: Float, y: Float, pressure: Float = 0, pen: Bool = false) {
        var payload = Data()
        var id = contactID.bigEndian
        payload.append(Data(bytes: &id, count: 2))
        payload.append(phase)
        var values = [x, y, pressure]
        for value in values {
            var bits = value.bitPattern.bigEndian
            payload.append(Data(bytes: &bits, count: 4))
        }
        payload.append(pen ? 1 : 0)
        send(DuoFrame(type: .input, flags: 0, payload: payload))
    }

    private func setStatus(_ value: String) {
        status = value
        DispatchQueue.main.async { self.onStatus?(value) }
    }
}
