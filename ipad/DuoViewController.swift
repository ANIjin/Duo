import UIKit

final class DuoViewController: UIViewController {
    private let imageView = UIImageView()
    private let statusLabel = UILabel()
    private let client = DuoClient()

    override var supportedInterfaceOrientations: UIInterfaceOrientationMask { .landscape }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        imageView.contentMode = .scaleAspectFit
        imageView.frame = view.bounds
        imageView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(imageView)
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
        client.onStatus = { [weak self] status in
            self?.statusLabel.text = "\(status)\nProtocol \(DuoClient.protocolVersion)\nConnect the iPad by USB."
            self?.statusLabel.isHidden = status == "Connected"
        }
        do {
            try client.start(port: 24862)
        } catch {
            statusLabel.text = error.localizedDescription
        }
    }

    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        UIApplication.shared.isIdleTimerDisabled = false
        client.stop()
    }
}
