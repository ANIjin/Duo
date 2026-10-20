# Duo iPad client

This directory contains the iPadOS client source layout. Open it in Xcode on
macOS and add the Swift files to an iOS/iPadOS app target. The transport uses
`NWListener` on the local usbmux-forwarded TCP endpoint; no Wi-Fi or LAN
address is required.

The checked-in [DuoClient.xcodeproj](./DuoClient.xcodeproj) can be built by
GitHub Actions. The `ipad-simulator` job performs an unsigned simulator build
and the `ipad-ipa` job performs an unsigned `iphoneos` build on every change.
It packages the app as `DuoClient-unsigned.ipa` without requiring certificates,
profiles, or GitHub environment variables.

The resulting artifact is not installable on an iPad as-is: Apple requires
code signing and provisioning for device installation. Sign the extracted
`Payload/DuoClient.app` with an Apple ID/development profile, AltStore, or
another sideloading tool before installing it.

The app bundle must retain `CFBundleExecutable=$(EXECUTABLE_NAME)` in
`DuoClient/Info.plist`; without it, Sideloadly reports
`MissingBundleExecutable` and refuses the IPA.
