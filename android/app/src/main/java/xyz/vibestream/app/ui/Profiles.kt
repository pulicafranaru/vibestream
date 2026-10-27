package xyz.vibestream.app.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.keyframes
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import xyz.vibestream.app.AppState
import xyz.vibestream.app.Debug
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.ApiException
import xyz.vibestream.app.api.Profile

// Long press enters Manage mode; a PIN is asked when choosing another locked profile and before editing.
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ProfilesView(dismissable: Boolean, onDone: () -> Unit) {
    var managing by remember { mutableStateOf(Debug.has("manageProfiles")) }
    var editing by remember { mutableStateOf<EditorTarget?>(null) }
    var asking by remember { mutableStateOf<Pair<Profile, Boolean>?>(null) }
    val haptic = LocalHapticFeedback.current
    val scope = rememberCoroutineScope()

    LaunchedEffect(managing) { if (managing) haptic.performHapticFeedback(HapticFeedbackType.LongPress) }
    LaunchedEffect(AppState.profiles) {
        Debug.int("askPin")?.let { id -> AppState.profiles.firstOrNull { it.id == id }?.let { asking = it to false } }
    }

    Box(
        Modifier.fillMaxSize().background(Palette.ground).pointerInput(Unit) {
            detectTapGestures(onTap = { managing = false }, onLongPress = { managing = true })
        },
    ) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
                .padding(top = if (dismissable) 24.dp else 80.dp, bottom = 40.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(30.dp),
        ) {
            androidx.compose.foundation.layout.BoxWithConstraints(Modifier.widthIn(max = 640.dp).fillMaxWidth().padding(horizontal = 24.dp)) {
                val columns = maxOf(1, ((maxWidth.value + 20) / 130).toInt())
                val tiles: List<@Composable () -> Unit> = AppState.profiles.map { profile ->
                    @Composable {
                        ProfileTile(profile, managing,
                            onTap = {
                                when {
                                    managing -> if (profile.locked) asking = profile to true else editing = EditorTarget(profile, null)
                                    profile.locked && profile.id != AppState.profile?.id -> asking = profile to false
                                    else -> scope.launch { AppState.pick(profile); onDone() }
                                }
                            },
                            onHold = { managing = true })
                    }
                } + if (managing || AppState.profiles.isEmpty()) listOf<@Composable () -> Unit>({ AddProfileTile { editing = EditorTarget(null, null) } }) else emptyList()
                Column(verticalArrangement = Arrangement.spacedBy(26.dp)) {
                    tiles.chunked(columns).forEach { row ->
                        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                            row.forEach { tile -> Box(Modifier.weight(1f), contentAlignment = Alignment.Center) { tile() } }
                            repeat(columns - row.size) { Spacer(Modifier.weight(1f)) }
                        }
                    }
                }
            }
            if (AppState.profiles.isNotEmpty()) {
                Text(if (managing) "Tap outside to finish" else "Tap and hold to edit profiles", fontSize = 13.sp, color = Palette.faint)
            }
        }
        if (dismissable) {
            Box(Modifier.align(Alignment.TopEnd).padding(8.dp).size(40.dp).background(Palette.fill, CircleShape).pressable(onClick = onDone),
                contentAlignment = Alignment.Center) { Icon(Icons.Filled.Close, "Close", tint = Color.White, modifier = Modifier.size(20.dp)) }
        }
    }

    asking?.let { (profile, toEdit) ->
        PinEntry(profile, if (toEdit) "Enter the PIN to edit this profile" else "Enter your PIN", onClose = { asking = null }) { pin ->
            val answer = runCatching { Api.checkPin(profile.id, pin) }.fold({ PinAnswer.Right }, { PinAnswer.of(it) })
            if (answer == PinAnswer.Right) {
                asking = null
                if (toEdit) editing = EditorTarget(profile, pin)
                else scope.launch { AppState.pick(profile, pin); onDone() }
            }
            answer
        }
    }
    editing?.let { target -> ProfileEditor(target.profile, target.pin) { editing = null } }
}

private data class EditorTarget(val profile: Profile?, val pin: String?)

@Composable
private fun AddProfileTile(onClick: () -> Unit) {
    Column(Modifier.width(110.dp).pressable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.size(100.dp).drawBehind {
            drawCircle(Palette.dim, style = Stroke(2.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 5.dp.toPx()))))
        }, contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.Add, null, tint = Palette.dim, modifier = Modifier.size(34.dp))
        }
        Text("Add Profile", fontSize = 15.sp, color = Palette.dim)
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ProfileTile(profile: Profile, managing: Boolean, onTap: () -> Unit, onHold: () -> Unit) {
    val current = profile.id == AppState.profile?.id
    Column(
        Modifier.width(110.dp).combinedClickable(remember { MutableInteractionSource() }, null, onClick = onTap, onLongClick = onHold),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box {
            Avatar(profile.avatar, 100.dp,
                if (current && !managing) Modifier.border(3.dp, Color.White, CircleShape) else Modifier)
            if (managing) {
                Box(Modifier.align(Alignment.BottomEnd).offset(6.dp, 6.dp).size(32.dp).background(Color.White, CircleShape),
                    contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Edit, null, tint = Color.Black, modifier = Modifier.size(16.dp))
                }
            }
        }
        Text(profile.name, fontSize = 15.sp, color = if (current) Color.White else Palette.dim)
    }
}

/** Outcome of a PIN attempt: the server answers 403 for wrong, 429 for too many. */
enum class PinAnswer(val message: String?) {
    Right(null), Wrong("Wrong PIN. Try again."), Mismatch("That does not match. Try again."),
    Wait("Too many tries. Wait 30 seconds."), Failed("Could not check it. Try again.");

    companion object {
        fun of(error: Throwable) = when ((error as? ApiException)?.code) {
            403 -> Wrong
            429 -> Wait
            else -> Failed
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PinEntry(profile: Profile?, title: String, subtitle: String? = null, onClose: () -> Unit, onEntered: suspend (String) -> PinAnswer) {
    var digits by remember(title) { mutableStateOf("") }
    var message by remember(title) { mutableStateOf<String?>(null) }
    var checking by remember { mutableStateOf(false) }
    val shake = remember { Animatable(0f) }

    LaunchedEffect(digits) {
        if (digits.length != 4 || checking) return@LaunchedEffect
        checking = true
        val answer = onEntered(digits)
        checking = false
        if (answer != PinAnswer.Right) {
            digits = ""
            message = answer.message
            shake.animateTo(0f, keyframes { durationMillis = 410; -12f at 70; 12f at 160; -12f at 250; 12f at 340 })
        }
    }

    ModalBottomSheet(onDismissRequest = onClose, containerColor = Palette.ground, sheetState = rememberModalBottomSheetState(true)) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp).padding(top = 10.dp, bottom = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
            profile?.let {
                Avatar(it.avatar, 84.dp)
                Text(it.name, fontSize = 15.sp, color = Palette.dim)
            }
            Text(title, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = Color.White, textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 6.dp))
            subtitle?.let { Text(it, fontSize = 13.sp, color = Palette.dim, textAlign = TextAlign.Center) }
            Box(Modifier.padding(top = 14.dp), contentAlignment = Alignment.Center) {
                Row(Modifier.offset { IntOffset(shake.value.dp.roundToPx(), 0) },
                    horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                    repeat(4) { i ->
                        val filled = i < digits.length
                        Box(Modifier.size(18.dp).border(2.dp, Color.White.copy(alpha = if (filled) 1f else 0.45f), CircleShape)
                            .background(if (filled) Color.White else Color.Transparent, CircleShape))
                    }
                }
            }
            Text(message ?: " ", fontSize = 13.sp, color = Palette.accent)
        }
        AppKeyboard(
            onType = { if (digits.length < 4 && !checking) { message = null; digits += it } },
            onDelete = { if (!checking) digits = digits.dropLast(1) },
            digits = true,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun ProfileEditor(profile: Profile?, unlocked: String?, onClose: () -> Unit) {
    val isNew = profile == null
    var name by remember { mutableStateOf(profile?.name.orEmpty()) }
    var typing by remember { mutableStateOf(profile == null) }
    var marked by remember { mutableStateOf(false) }
    var avatar by remember { mutableStateOf(profile?.avatar ?: AppState.avatarChoices.firstOrNull() ?: "crimson-smile") }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirmingDelete by remember { mutableStateOf(false) }
    var pin by remember { mutableStateOf(unlocked) }
    var hasPin by remember { mutableStateOf(profile?.locked ?: false) }
    var choosingPin by remember { mutableStateOf(false) }
    var chosen by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    ModalBottomSheet(onDismissRequest = onClose, containerColor = Palette.ground, sheetState = rememberModalBottomSheetState(true)) {
        Column(Modifier.fillMaxWidth().weight(1f, fill = false).verticalScroll(rememberScrollState()).padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(22.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("Cancel", fontSize = 17.sp, color = Color.White, modifier = Modifier.pressable(onClick = onClose))
                Text(if (isNew) "New Profile" else "Edit Profile", fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
                    color = Color.White, textAlign = TextAlign.Center, modifier = Modifier.weight(1f))
                val can = name.isNotBlank() && !saving
                Text("Save", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = if (can) Color.White else Palette.faint,
                    modifier = Modifier.pressable(can) {
                        saving = true
                        error = null
                        scope.launch {
                            runCatching {
                                val clean = name.trim()
                                if (profile != null) Api.updateProfile(profile.id, clean, avatar, pin) else Api.createProfile(clean, avatar)
                                AppState.loadProfiles(keepingSelection = true)
                                onClose()
                            }.onFailure { error = it.message }
                            saving = false
                        }
                    })
            }
            Avatar(avatar, 110.dp)
            KeyText(name, "Name", typing, TextStyle(color = Color.White, fontSize = 20.sp),
                Modifier.fillMaxWidth().background(Palette.fill, RoundedCornerShape(14.dp)).padding(12.dp)
                    .pressable { if (!typing) { typing = true; marked = name.isNotEmpty() } },
                selected = marked, centred = true)
            error?.let { Text(it, fontSize = 13.sp, color = Palette.accent, textAlign = TextAlign.Center) }

            val (colour, face) = AvatarArt.parts(avatar)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterHorizontally),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                AvatarArt.faces.forEach { f ->
                    val option = "${colour.id}-$f"
                    Avatar(option, 58.dp, Modifier.border(if (option == avatar) 3.dp else 0.dp, Color.White, CircleShape)
                        .pressable { avatar = option; typing = false })
                }
            }
            FlowRow(Modifier.widthIn(max = 220.dp), horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally),
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                AvatarArt.colours.forEach { c ->
                    Box(Modifier.size(34.dp).border(if (c.id == colour.id) 2.dp else 0.dp, Color.White, CircleShape)
                        .pressable { avatar = "${c.id}-$face"; typing = false }.padding(4.dp)
                        .background(Brush.verticalGradient(listOf(c.top, c.bottom)), CircleShape))
                }
            }

            if (!isNew) {
                Row(Modifier.fillMaxWidth().background(Palette.fill, RoundedCornerShape(14.dp)).padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Icon(Icons.Outlined.Lock, null, tint = Palette.dim, modifier = Modifier.size(18.dp))
                    Text(if (hasPin) "PIN on" else "No PIN", fontSize = 15.sp, color = Palette.dim)
                    Spacer(Modifier.weight(1f))
                    Text(if (hasPin) "Change" else "Add a PIN", fontSize = 15.sp, color = Color.White,
                        modifier = Modifier.pressable { chosen = null; choosingPin = true })
                    if (hasPin) Text("Remove", fontSize = 15.sp, color = Palette.accent, modifier = Modifier.pressable {
                        error = null
                        scope.launch {
                            runCatching { Api.setPin(profile!!.id, null, pin); pin = null; hasPin = false; AppState.loadProfiles(true) }
                                .onFailure { error = it.message }
                        }
                    })
                }
                Pill(false, Modifier.fillMaxWidth(), onClick = { confirmingDelete = true }) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(Icons.Outlined.Delete, null, tint = Palette.accent)
                        Text("Delete Profile", fontSize = 17.sp, color = Palette.accent)
                    }
                }
            }
        }
        if (typing) {
            AppKeyboard(
                onType = { typed -> name = if (marked) typed else name + typed; marked = false },
                onDelete = { name = if (marked) "" else name.dropLast(1); marked = false },
                action = "Done",
                onAction = { typing = false; marked = false },
                capitalise = true,
                atWordStart = name.isEmpty() || marked || name.endsWith(" "),
            )
        }
    }

    if (choosingPin && profile != null) {
        PinEntry(profile, if (chosen == null) "Choose a PIN" else "Enter it again",
            if (chosen == null) "Four digits, asked for when someone chooses this profile." else null,
            onClose = { choosingPin = false }) { typed ->
            val first = chosen
            if (first == null) { chosen = typed; return@PinEntry PinAnswer.Right }
            if (typed != first) return@PinEntry PinAnswer.Mismatch
            runCatching { Api.setPin(profile.id, typed, pin) }.exceptionOrNull()?.let { return@PinEntry PinAnswer.of(it) }
            pin = typed
            hasPin = true
            if (profile.id == AppState.profile?.id) AppState.profilePin = typed
            choosingPin = false
            AppState.loadProfiles(keepingSelection = true)
            PinAnswer.Right
        }
    }
    if (confirmingDelete && profile != null) {
        AlertDialog(
            onDismissRequest = { confirmingDelete = false },
            title = { Text("Delete ${profile.name}?") },
            text = { Text("Their progress and ratings are removed too.") },
            confirmButton = {
                TextButton({
                    confirmingDelete = false
                    saving = true
                    error = null
                    scope.launch {
                        runCatching { Api.deleteProfile(profile.id, pin); AppState.profileWasDeleted(profile.id); onClose() }
                            .onFailure {
                                error = if ((it as? ApiException)?.code == 400) "This is the only profile, so it cannot be deleted." else it.message
                            }
                        saving = false
                    }
                }) { Text("Delete Profile", color = Color(0xFFFF5A6E)) }
            },
            dismissButton = { TextButton({ confirmingDelete = false }) { Text("Cancel", color = Color.White) } },
            containerColor = Color(0xFF242424),
        )
    }
}
