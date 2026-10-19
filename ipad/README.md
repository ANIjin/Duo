# Duo iPad client

This directory contains the iPadOS client source layout. Open it in Xcode on
macOS and add the Swift files to an iOS/iPadOS app target. The transport uses
`NWListener` on the local usbmux-forwarded TCP endpoint; no Wi-Fi or LAN
address is required.

The checked-in [DuoClient.xcodeproj](./DuoClient.xcodeproj) can be built by
GitHub Actions. The `ipad-simulator` job performs an unsigned simulator build
on every change. The `ipad-ipa` job runs for a tag or manual dispatch and
uploads a sideloadable IPA artifact.

Configure the `ios-release` environment with these secrets:

- `IOS_CERTIFICATE_BASE64`: base64-encoded Apple Distribution `.p12`
- `IOS_CERTIFICATE_PASSWORD`
- `IOS_PROVISION_PROFILE_BASE64`: base64-encoded App Store/ad hoc profile
- `IOS_PROVISIONING_PROFILE_NAME`
- `IOS_TEAM_ID`
- `IOS_KEYCHAIN_PASSWORD`
- `IOS_EXPORT_OPTIONS_PLIST_BASE64`

The export options must match the profile type. For ad hoc sideloading, use
`method: ad-hoc`, the `com.duo.display` bundle identifier, and the registered
iPad UDIDs in the provisioning profile.

The app must be provisioned for the target iPad. A free Apple ID profile
normally requires re-signing after seven days.
