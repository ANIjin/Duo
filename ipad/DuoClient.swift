import Foundation
import Network
import UIKit

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
    var onStatus: ((String) -> Void)?

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
        var payload = Data([DuoClient.protocolVersion])
        var width = UInt16(pixels.width).bigEndian
        var height = UInt16(pixels.height).bigEndian
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

    private func handle(_ frame: DuoFrame) {
        switch frame.type {
        case .frame:
            guard frame.payload.count > 8 else { return }
            let imageData = frame.payload.dropFirst(8)
            if let image = UIImage(data: imageData) {
                DispatchQueue.main.async { self.onImage?(image) }
            }
        case .config:
            guard frame.payload.count >= 11 else { return }
            let codec = frame.payload[0]
            if codec == 1 {
                setStatus("Streaming JPEG")
            } else if codec == 2 {
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

    private func setStatus(_ value: String) {
        status = value
        DispatchQueue.main.async { self.onStatus?(value) }
    }
}
