import UIKit
import AVFoundation

final class DuoViewController: UIViewController {
    private let imageView = UIImageView()
    private let statusLabel = UILabel()
    private let client = DuoClient()
    private let videoLayer = AVSampleBufferDisplayLayer()

    override var supportedInterfaceOrientations: UIInterfaceOrientationMask { .landscape }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        view.insetsLayoutMarginsFromSafeArea = false
        additionalSafeAreaInsets = .zero
        imageView.contentMode = .scaleToFill
        imageView.clipsToBounds = true
        imageView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(imageView)
        NSLayoutConstraint.activate([
            imageView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            imageView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            imageView.topAnchor.constraint(equalTo: view.topAnchor),
            imageView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        videoLayer.videoGravity = .resize
        videoLayer.frame = view.bounds
        configureDisplayClock()
        view.layer.addSublayer(videoLayer)
        statusLabel.textColor = .white
        statusLabel.textAlignment = .center
        statusLabel.numberOfLines = 0
        statusLabel.text = "Waiting for PC\nConnect the iPad by USB."
        statusLabel.frame = view.bounds
        statusLabel.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(statusLabel)
        UIApplication.shared.isIdleTimerDisabled = true
        client.onImage = { [weak self] image in
            self?.imageView.image = image
            self?.statusLabel.isHidden = true
        }
        client.onSampleBuffer = { [weak self] sample in
            guard let self else { return }
            if self.videoLayer.status == .failed {
                self.videoLayer.flush()
            }
            if let timebase = self.videoLayer.controlTimebase {
                let pts = CMSampleBufferGetPresentationTimeStamp(sample)
                CMTimebaseSetTime(timebase, time: pts)
                CMTimebaseSetRate(timebase, rate: 1)
            }
            if self.videoLayer.isReadyForMoreMediaData {
                self.videoLayer.enqueue(sample)
            } else {
                self.client.requestKeyframe()
            }
            self.imageView.isHidden = true
            self.statusLabel.isHidden = true
        }
        client.onStatus = { [weak self] status in
            let streaming = status.hasPrefix("Streaming")
            self?.statusLabel.text = "\(status)\nProtocol \(DuoClient.protocolVersion)\nConnect the iPad by USB."
            self?.statusLabel.isHidden = status == "Connected" || streaming
        }
        do {
            try client.start(port: 24862)
        } catch {
            statusLabel.text = error.localizedDescription
        }
    }

    private func configureDisplayClock() {
        var timebase: CMTimebase?
        let status = CMTimebaseCreateWithSourceClock(
            allocator: kCFAllocatorDefault,
            sourceClock: CMClockGetHostTimeClock(),
            timebaseOut: &timebase
        )
        guard status == noErr, let timebase else { return }
        CMTimebaseSetTime(timebase, time: .zero)
        CMTimebaseSetRate(timebase, rate: 1)
        videoLayer.controlTimebase = timebase
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        videoLayer.frame = view.bounds
    }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        send(touches, phase: 0)
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        send(touches, phase: 1)
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        send(touches, phase: 2)
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
        send(touches, phase: 3)
    }

    private func send(_ touches: Set<UITouch>, phase: UInt8) {
        for touch in touches {
            let point = touch.location(in: view)
            let x = Float(max(0, min(1, point.x / view.bounds.width)))
            let y = Float(max(0, min(1, point.y / view.bounds.height)))
            let pressure = touch.type == .pencil ? touch.force / max(touch.maximumPossibleForce, 1) : 0
            client.sendInput(
                contactID: UInt16(abs(ObjectIdentifier(touch).hashValue) % Int(UInt16.max)),
                phase: phase,
                x: x,
                y: y,
                pressure: Float(pressure),
                pen: touch.type == .pencil
            )
        }
    }

    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        UIApplication.shared.isIdleTimerDisabled = false
        client.stop()
    }
}
