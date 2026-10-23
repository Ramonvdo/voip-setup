// Linphone Dialer: click a phone number anywhere on a Mac and Linphone dials it.
//
// Linphone 6.2 does register for tel: links, but a call it starts from a link (or from its
// command line) goes out with media encryption forced to none, whatever linphonerc says.
// A carrier that requires SRTP answers "488 Media Encryption Required", so the click looks
// like it did nothing. A call started from Linphone's own dialer uses the SRTP setting, so
// this app takes the link and presses the buttons for you, through the accessibility API:
// Calls > New call > dialer > number > Call.
//
// Opened by hand, it offers to become the Mac's app for tel: and callto: links and asks for
// Accessibility access. Build and install: zsh build.sh, next to this file.

import Cocoa

let linphoneID = "com.belledonnecommunications.linphone"

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var gotLink = false

    func application(_ application: NSApplication, open urls: [URL]) {
        gotLink = true
        if let url = urls.first { dial(url) }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // A link arrives just after launch; no link means it was opened by hand.
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
            if !self.gotLink { self.setUp() }
        }
    }

    private func setUp() {
        let me = Bundle.main.bundleURL
        let group = DispatchGroup()
        for scheme in ["tel", "callto"] {
            group.enter()
            NSWorkspace.shared.setDefaultApplication(at: me, toOpenURLsWithScheme: scheme) { _ in group.leave() }
        }
        group.notify(queue: .main) {
            let handler = NSWorkspace.shared.urlForApplication(toOpen: URL(string: "tel:0")!)
            let trusted = AXIsProcessTrustedWithOptions(
                [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary)
            var text = handler == me
                ? "Phone links now open in Linphone Dialer."
                : "Phone links still open in another app. Open Linphone Dialer again and accept the change."
            if !trusted {
                text += "\n\nTurn on Linphone Dialer in System Settings > Privacy & Security > Accessibility, "
                    + "so it can press Linphone's buttons."
            }
            self.finish("Linphone Dialer", text)
        }
    }

    private func dial(_ url: URL) {
        let number = String(url.absoluteString.drop { $0 != ":" }.dropFirst()
            .prefix { $0 != ";" && $0 != "?" }
            .filter { $0.isNumber || $0 == "+" })
        guard !number.isEmpty else { return NSApp.terminate(nil) }
        guard let linphone = NSWorkspace.shared.urlForApplication(withBundleIdentifier: linphoneID) else {
            return failed(number, "Linphone isn't installed.")
        }
        guard AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary) else {
            return failed(number, "Linphone Dialer needs Accessibility access. Turn it on in System Settings > "
                + "Privacy & Security > Accessibility, then click the number again.")
        }
        let config = NSWorkspace.OpenConfiguration()
        config.activates = true
        NSWorkspace.shared.openApplication(at: linphone, configuration: config) { app, _ in
            let ok = app.map { LinphoneUI(pid: $0.processIdentifier).dial(number) } ?? false
            Task { @MainActor in
                if ok { NSApp.terminate(nil) } else { self.failed(number, "Linphone didn't show its dialer in time.") }
            }
        }
    }

    /// The number goes on the clipboard, so the call is one paste away.
    private func failed(_ number: String, _ reason: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(number, forType: .string)
        finish("Couldn't dial \(number) in Linphone", reason + "\n\nThe number is on your clipboard.")
    }

    private func finish(_ title: String, _ text: String) {
        NSApp.activate()
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = text
        alert.runModal()
        NSApp.terminate(nil)
    }
}

/// Linphone's window, read and pressed through the accessibility API. Elements are found by
/// their accessible names, as Linphone 6.2 labels them.
struct LinphoneUI {
    let app: AXUIElement

    init(pid: pid_t) { app = AXUIElementCreateApplication(pid) }

    func dial(_ number: String) -> Bool {
        guard wait({ !named("Open calls pages").isEmpty }, seconds: 15) else { return false }
        if named("Close numeric pad").isEmpty {
            named("Open calls pages").first.map(press)
            if wait({ !named("Create new call").isEmpty }, seconds: 2) { named("Create new call").first.map(press) }
            guard wait({ !named("Search bar : Find contact").isEmpty }) else { return false }
            // The panel's dialer button only shows while its field is empty. The first
            // "Open dialer" belongs to the top bar; the panel's own comes after it.
            named("Clear text input").forEach(press)
            guard wait({ named("Open dialer").count >= 2 }) else { return false }
            named("Open dialer").last.map(press)
        }
        guard wait({ !named("Close numeric pad").isEmpty }),
              let field = named("Search bar : Find contact").first else { return false }
        AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString, number as CFString)
        usleep(400_000)
        // The keypad's Call button comes after the call history's own Call button.
        guard let call = named("Call").last else { return false }
        press(call)
        return true
    }

    private func attribute(_ element: AXUIElement, _ name: String) -> AnyObject? {
        var value: AnyObject?
        AXUIElementCopyAttributeValue(element, name as CFString, &value)
        return value
    }

    private func tree(_ element: AXUIElement) -> [AXUIElement] {
        [element] + ((attribute(element, kAXChildrenAttribute) as? [AXUIElement]) ?? []).flatMap(tree)
    }

    private func named(_ name: String) -> [AXUIElement] {
        let windows = (attribute(app, kAXWindowsAttribute) as? [AXUIElement]) ?? []
        return windows.flatMap(tree).filter {
            attribute($0, kAXTitleAttribute) as? String == name || attribute($0, kAXDescriptionAttribute) as? String == name
        }
    }

    private func press(_ element: AXUIElement) {
        AXUIElementPerformAction(element, kAXPressAction as CFString)
        usleep(300_000)
    }

    private func wait(_ ready: () -> Bool, seconds: Double = 5) -> Bool {
        let deadline = Date().addingTimeInterval(seconds)
        while !ready() {
            if Date() > deadline { return false }
            usleep(100_000)
        }
        return true
    }
}

MainActor.assumeIsolated {
    let delegate = AppDelegate()
    NSApplication.shared.delegate = delegate
    withExtendedLifetime(delegate) { NSApplication.shared.run() }
}
