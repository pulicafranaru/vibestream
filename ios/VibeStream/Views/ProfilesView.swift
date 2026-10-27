import SwiftUI

/// A profile with a PIN asks for it when chosen and before it is edited. Holding a face enters Manage mode.
struct ProfilesView: View {
    @Environment(AppState.self) private var state
    @Environment(\.dismiss) private var dismiss
    var dismissable: Bool

    @State private var managing = false
    @State private var editing: EditTarget?
    @State private var asking: PinAsk?
    /// Run once the PIN sheet has gone, so a second sheet never rises while the first is closing.
    @State private var afterPin: (() -> Void)?
    @State private var height: CGFloat = 0

    /// nil profile means "create". `pin` is the profile's, when it was just typed.
    struct EditTarget: Identifiable {
        let profile: Profile?
        var pin: String? = nil
        var id: Int { profile?.id ?? -1 }
    }

    struct PinAsk: Identifiable {
        let profile: Profile
        let toEdit: Bool
        var id: String { "\(profile.id)-\(toEdit)" }
    }

    private let columns = [GridItem(.adaptive(minimum: 110), spacing: 20)]

    var body: some View {
        ZStack {
            Palette.ground.ignoresSafeArea()

            ScrollView {
                VStack(spacing: 30) {
                    LazyVGrid(columns: columns, spacing: 26) {
                        ForEach(state.profiles) { profile in
                            tile(profile)
                                .contentShape(.rect)
                                .onTapGesture {
                                    if managing {
                                        if profile.locked {
                                            asking = PinAsk(profile: profile, toEdit: true)
                                        } else {
                                            editing = EditTarget(profile: profile)
                                        }
                                    } else if profile.locked && profile.id != state.profile?.id {
                                        asking = PinAsk(profile: profile, toEdit: false)
                                    } else {
                                        Task { await state.pick(profile); dismiss() }
                                    }
                                }
                                .onLongPressGesture(minimumDuration: 0.45) {
                                    withAnimation(.snappy) { managing = true }
                                }
                                .accessibilityAddTraits(.isButton)
                                .accessibilityAction(named: "Manage Profiles") {
                                    withAnimation(.snappy) { managing = true }
                                }
                        }

                        if managing || state.profiles.isEmpty {
                            Button { editing = EditTarget(profile: nil) } label: {
                                VStack(spacing: 10) {
                                    Circle()
                                        .strokeBorder(Palette.dim,
                                                      style: StrokeStyle(lineWidth: 2, dash: [6, 5]))
                                        .frame(width: 100, height: 100)
                                        .overlay(
                                            Image(systemName: "plus")
                                                .font(.system(size: 30, weight: .regular))
                                                .foregroundStyle(Palette.dim)
                                        )
                                    Text("Add Profile")
                                        .font(.subheadline).foregroundStyle(Palette.dim)
                                }
                            }
                            .buttonStyle(.plain)
                            .transition(.opacity.combined(with: .scale(scale: 0.85)))
                        }
                    }
                    .padding(.horizontal, 24)

                    if !state.profiles.isEmpty {
                        Text(managing ? "Tap outside to finish" : "Tap and hold to edit profiles")
                            .font(.footnote)
                            .foregroundStyle(Palette.faint)
                            .contentTransition(.opacity)
                    }
                }
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
                .padding(.top, dismissable ? 24 : 80)
                .padding(.bottom, 40)
                // At least screen height, so a tap off the faces ends Manage mode and a hold starts it.
                .frame(minHeight: height, alignment: .top)
                .contentShape(.rect)
                .onTapGesture {
                    if managing { withAnimation(.snappy) { managing = false } }
                }
                .onLongPressGesture(minimumDuration: 0.45) {
                    withAnimation(.snappy) { managing = true }
                }
            }
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height = $0 }
        }
        .sensoryFeedback(.impact(weight: .medium), trigger: managing) { _, now in now }
        #if DEBUG
        // -manageProfiles: open in Manage mode, as a script cannot long press.
        .onAppear {
            let arguments = ProcessInfo.processInfo.arguments
            if arguments.contains("-manageProfiles") { managing = true }
            if let flag = arguments.firstIndex(of: "-askPin"), flag + 1 < arguments.count,
               let found = state.profiles.first(where: { String($0.id) == arguments[flag + 1] }) {
                asking = PinAsk(profile: found, toEdit: false)
            }
        }
        #endif
        .toolbar {
            if dismissable {
                ToolbarItem(placement: .topBarTrailing) {
                    CloseButton { dismiss() }
                }
            }
        }
        .sheet(item: $editing) { target in
            ProfileEditor(profile: target.profile, unlocked: target.pin)
                .environment(state)
        }
        .sheet(item: $asking, onDismiss: {
            afterPin?()
            afterPin = nil
        }) { ask in
            PinEntry(profile: ask.profile,
                     title: ask.toEdit ? "Enter the PIN to edit this profile" : "Enter your PIN") { pin in
                do {
                    try await APIClient.shared.checkPin(ask.profile.id, pin: pin)
                } catch {
                    return PinAnswer(error)
                }
                let profile = ask.profile
                afterPin = ask.toEdit
                    ? { editing = EditTarget(profile: profile, pin: pin) }
                    : {
                        Cast.shared.unlocked(profile.id, pin: pin)
                        Task { await state.pick(profile); dismiss() }
                    }
                asking = nil
                return .right
            }
        }
    }

    private func tile(_ profile: Profile) -> some View {
        VStack(spacing: 10) {
            Avatar(id: profile.avatar, size: 100)
                .overlay {
                    Circle()
                        .stroke(.white, lineWidth: profile.id == state.profile?.id && !managing ? 3 : 0)
                }
                .overlay(alignment: .bottomTrailing) {
                    if managing {
                        Image(systemName: "pencil")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(.black)
                            .frame(width: 32, height: 32)
                            .background(.white, in: .circle)
                            .offset(x: 6, y: 6)
                    }
                }
            Text(profile.name)
                .font(.subheadline)
                .foregroundStyle(profile.id == state.profile?.id ? .white : Palette.dim)
        }
    }
}

enum PinAnswer {
    case right, wrong, mismatch, wait, failed

    /// From the server's refusal: 403 wrong, 429 too many in a row.
    init(_ error: Error) {
        switch error {
        case APIError.status(403, _): self = .wrong
        case APIError.status(429, _): self = .wait
        default: self = .failed
        }
    }

    var message: String? {
        switch self {
        case .right: nil
        case .wrong: "Wrong PIN. Try again."
        case .mismatch: "That does not match. Try again."
        case .wait: "Too many tries. Wait 30 seconds."
        case .failed: "Could not check it. Try again."
        }
    }
}

/// The fourth digit checks the PIN, with no button to press.
/// The iPad has no number pad keyboard (it floats a keypad over the sheet), so keys are drawn here.
struct PinEntry: View {
    @Environment(\.dismiss) private var dismiss
    let profile: Profile?
    let title: String
    var subtitle: String? = nil
    let onEntered: (String) async -> PinAnswer

    @State private var digits = ""
    @State private var message: String?
    @State private var shakes = 0
    @State private var checking = false
    @FocusState private var typing: Bool
    @FocusState private var keys: Bool
    private let ownPad = UIDevice.current.userInterfaceIdiom == .pad

    var body: some View {
        // No navigation stack on the iPad: it has no intrinsic height, so the sheet could not fit the keys.
        Group {
            if ownPad {
                form.overlay(alignment: .topTrailing) {
                    CloseButton { dismiss() }
                        .buttonStyle(.glass)
                        .buttonBorderShape(.circle)
                        .controlSize(.large)
                        .padding(16)
                }
            } else {
                NavigationStack {
                    form.toolbar {
                        ToolbarItem(placement: .topBarTrailing) { CloseButton { dismiss() } }
                    }
                }
            }
        }
        .presentationDetents(ownPad ? [.large] : [.medium, .large])
        // The iPad's form sheet has a fixed height that cut off the bottom row of keys.
        .presentationSizing(.form.fitted(horizontal: false, vertical: true))
        .onAppear {
            if ownPad { keys = true } else { typing = true }
            #if DEBUG
            // -typePin 0000,1234: type these in turn.
            let arguments = ProcessInfo.processInfo.arguments
            if let flag = arguments.firstIndex(of: "-typePin"), flag + 1 < arguments.count {
                let codes = arguments[flag + 1].split(separator: ",")
                Task {
                    for code in codes {
                        try? await Task.sleep(for: .seconds(2))
                        for digit in code {
                            digits.append(digit)
                            try? await Task.sleep(for: .milliseconds(250))
                        }
                    }
                }
            }
            #endif
        }
        .onChange(of: title) {
            digits = ""
            message = nil
        }
        .onChange(of: digits) { _, now in
            let clean = String(now.filter(\.isASCIIDigit).prefix(4))
            if clean != now { digits = clean; return }
            if !clean.isEmpty { message = nil }
            guard clean.count == 4, !checking else { return }
            checking = true
            Task {
                let answer = await onEntered(clean)
                checking = false
                guard answer != .right else { return }
                digits = ""
                message = answer.message
                shakes += 1
            }
        }
    }

    private var form: some View {
        VStack(spacing: 14) {
            if let profile {
                Avatar(id: profile.avatar, size: 84)
                Text(profile.name).font(.subheadline).foregroundStyle(Palette.dim)
            }
            Text(title).font(.title3.weight(.semibold)).multilineTextAlignment(.center)
                .padding(.top, 6)
            if let subtitle {
                Text(subtitle).font(.footnote).foregroundStyle(Palette.dim).multilineTextAlignment(.center)
            }
            HStack(spacing: 20) {
                ForEach(0..<4, id: \.self) { i in
                    Circle()
                        .strokeBorder(.white.opacity(i < digits.count ? 1 : 0.45), lineWidth: 2)
                        .background(Circle().fill(i < digits.count ? .white : .clear))
                        .frame(width: 18, height: 18)
                }
            }
            // Hidden field at an ordinary size: one a point wide keeps its caret at the start and reverses the digits.
            .background {
                if !ownPad {
                    TextField("", text: $digits)
                        .keyboardType(.numberPad)
                        .textContentType(.oneTimeCode)
                        .focused($typing)
                        .frame(width: 160, height: 30)
                        .opacity(0.01)
                        .accessibilityLabel(title)
                }
            }
            .padding(.top, 14)
            .keyframeAnimator(initialValue: 0.0, trigger: shakes) { dots, x in
                dots.offset(x: x)
            } keyframes: { _ in
                KeyframeTrack {
                    LinearKeyframe(-12, duration: 0.07)
                    LinearKeyframe(12, duration: 0.09)
                    LinearKeyframe(-12, duration: 0.09)
                    LinearKeyframe(12, duration: 0.09)
                    LinearKeyframe(0, duration: 0.07)
                }
            }
            .contentShape(.rect)
            .onTapGesture { typing = true }
            Text(message ?? " ")
                .font(.footnote)
                .foregroundStyle(Palette.accent)
            if ownPad {
                PinPad(press: press).padding(.top, 10)
            } else {
                Spacer()
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 30)
        .padding(.bottom, ownPad ? 40 : 0)
        .frame(maxWidth: .infinity)
        .background(Palette.ground)
        .focusable(ownPad)
        .focused($keys)
        .focusEffectDisabled()
        .onKeyPress(phases: .down) { key in
            guard ownPad else { return .ignored }
            if key.key == .delete { press(nil); return .handled }
            guard let digit = key.characters.first, digit.isASCIIDigit else { return .ignored }
            press(digit)
            return .handled
        }
    }

    private func press(_ digit: Character?) {
        guard !checking else { return }
        if let digit {
            if digits.count < 4 { digits.append(digit) }
        } else if !digits.isEmpty {
            digits.removeLast()
        }
    }
}

/// The digits on screen, with Delete where the phone's pad has it.
private struct PinPad: View {
    let press: (Character?) -> Void
    private let rows: [[Character]] = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]]

    var body: some View {
        Grid(horizontalSpacing: 22, verticalSpacing: 16) {
            ForEach(rows, id: \.self) { row in
                GridRow {
                    ForEach(row, id: \.self) { digit in key(digit) }
                }
            }
            GridRow {
                Color.clear.frame(width: Self.size, height: Self.size)
                key("0")
                Button { press(nil) } label: {
                    Image(systemName: "delete.left").font(.title2)
                }
                .buttonStyle(PinKeyStyle(filled: false))
                .accessibilityLabel("Delete")
            }
        }
    }

    static let size: CGFloat = 80

    private func key(_ digit: Character) -> some View {
        Button { press(digit) } label: {
            Text(String(digit)).font(.system(size: 32, weight: .semibold))
        }
        .buttonStyle(PinKeyStyle(filled: true))
    }
}

private struct PinKeyStyle: ButtonStyle {
    let filled: Bool
    private static let key = Color(red: 0.220, green: 0.180, blue: 0.149)   // #382e26

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(configuration.isPressed ? .black : .white)
            .frame(width: PinPad.size, height: PinPad.size)
            .background(Circle().fill(configuration.isPressed ? .white : filled ? Self.key : .clear))
            .contentShape(Circle())
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

private extension Character {
    var isASCIIDigit: Bool { isASCII && isNumber }
}

struct ProfileEditor: View {
    @Environment(AppState.self) private var state
    @Environment(\.dismiss) private var dismiss

    let profile: Profile?
    var unlocked: String? = nil

    @State private var name = ""
    /// Selected whole when tapped, so typing replaces the name.
    @State private var nameSelection: TextSelection?
    @FocusState private var naming: Bool
    @State private var avatar = "crimson-smile"
    @State private var saving = false
    @State private var error: String?
    @State private var confirmingDelete = false
    @State private var pin: String?
    @State private var hasPin = false
    @State private var choosingPin = false
    @State private var chosen: String?

    private var isNew: Bool { profile == nil }
    private let columns = [GridItem(.adaptive(minimum: 62), spacing: 12)]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 22) {
                    Avatar(id: avatar, size: 110).padding(.top, 8)

                    TextField("Name", text: $name, selection: $nameSelection)
                        .focused($naming)
                        .onChange(of: naming) { _, now in
                            guard now, !name.isEmpty else { return }
                            // A beat after focus, or the field puts its own
                            // caret over the selection.
                            Task {
                                try? await Task.sleep(for: .milliseconds(50))
                                nameSelection = TextSelection(range: name.startIndex..<name.endIndex)
                            }
                        }
                        .textFieldStyle(.plain)
                        .font(.title3)
                        .multilineTextAlignment(.center)
                        .padding(12)
                        .glassCard()

                    if let error {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(Palette.accent)
                            .multilineTextAlignment(.center)
                    }

                    let parts = AvatarArt.parts(avatar)
                    LazyVGrid(columns: columns, spacing: 12) {
                        ForEach(AvatarArt.faces, id: \.self) { face in
                            let option = "\(parts.colour.id)-\(face)"
                            Button { avatar = option } label: {
                                Avatar(id: option, size: 58)
                                    .overlay {
                                        Circle()
                                            .stroke(.white, lineWidth: option == avatar ? 3 : 0)
                                    }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    LazyVGrid(columns: Array(repeating: GridItem(.fixed(34), spacing: 10), count: 5), spacing: 10) {
                        ForEach(AvatarArt.colours, id: \.id) { colour in
                            Button { avatar = "\(colour.id)-\(parts.face)" } label: {
                                Circle()
                                    .fill(LinearGradient(colors: [colour.top, colour.bottom],
                                                         startPoint: .top, endPoint: .bottom))
                                    .frame(width: 26, height: 26)
                                    .padding(3)
                                    .overlay {
                                        Circle().stroke(.white, lineWidth: colour.id == parts.colour.id ? 2 : 0)
                                    }
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel(colour.id)
                        }
                    }

                    if !isNew {
                        HStack(spacing: 10) {
                            Image(systemName: "lock")
                                .foregroundStyle(Palette.dim)
                            Text(hasPin ? "PIN on" : "No PIN")
                                .foregroundStyle(Palette.dim)
                            Spacer()
                            Button(hasPin ? "Change" : "Add a PIN") {
                                chosen = nil
                                choosingPin = true
                            }
                            if hasPin {
                                Button("Remove", role: .destructive) { removePin() }
                                    .foregroundStyle(Palette.accent)
                            }
                        }
                        .font(.subheadline)
                        .padding(14)
                        .glassCard()

                        Button(role: .destructive) {
                            confirmingDelete = true
                        } label: {
                            Label("Delete Profile", systemImage: "trash")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.glass)
                        .foregroundStyle(Palette.accent)
                        .controlSize(.large)
                        // On the button so the iPad popover points at it.
                        .confirmationDialog(
                            "Delete \(profile?.name ?? "")?",
                            isPresented: $confirmingDelete, titleVisibility: .visible
                        ) {
                            Button("Delete Profile", role: .destructive) { remove() }
                        } message: {
                            Text("Their progress and ratings are removed too.")
                        }
                        .padding(.top, 6)
                    }
                }
                .padding(20)
            }
            .background(Palette.ground)
            .navigationTitle(isNew ? "New Profile" : "Edit Profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { save() }
                        .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || saving)
                }
            }
        }
        .onAppear {
            name = profile?.name ?? ""
            avatar = profile?.avatar ?? state.avatarChoices.first ?? "crimson-smile"
            pin = unlocked
            hasPin = profile?.locked ?? false
        }
        .sheet(isPresented: $choosingPin) {
            PinEntry(profile: profile,
                     title: chosen == nil ? "Choose a PIN" : "Enter it again",
                     subtitle: chosen == nil ? "Four digits, asked for when someone chooses this profile." : nil) { typed in
                guard let first = chosen else {
                    chosen = typed
                    return .right
                }
                guard typed == first, let profile else { return .mismatch }
                do {
                    try await APIClient.shared.setPin(profile.id, pin: typed, current: pin)
                } catch {
                    return PinAnswer(error)
                }
                pin = typed
                hasPin = true
                choosingPin = false
                await state.loadProfiles(keepingSelection: true)
                return .right
            }
        }
    }

    private func removePin() {
        guard let profile else { return }
        error = nil
        Task {
            do {
                try await APIClient.shared.setPin(profile.id, pin: nil, current: pin)
                pin = nil
                hasPin = false
                await state.loadProfiles(keepingSelection: true)
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func save() {
        let clean = name.trimmingCharacters(in: .whitespaces)
        saving = true
        error = nil
        Task {
            do {
                if let profile {
                    try await APIClient.shared.updateProfile(profile.id, name: clean, avatar: avatar, pin: pin)
                } else {
                    _ = try await APIClient.shared.createProfile(name: clean, avatar: avatar)
                }
                await state.loadProfiles(keepingSelection: true)
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
            saving = false
        }
    }

    private func remove() {
        guard let profile else { return }
        saving = true
        error = nil
        Task {
            do {
                try await APIClient.shared.deleteProfile(profile.id, pin: pin)
                await state.profileWasDeleted(profile.id)
                dismiss()
            } catch {
                // The server refuses to remove the last profile with a 400.
                self.error = "\(error.localizedDescription)".contains("400")
                    ? "This is the only profile, so it cannot be deleted."
                    : error.localizedDescription
            }
            saving = false
        }
    }
}
