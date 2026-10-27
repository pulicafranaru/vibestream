package xyz.vibestream.app.ui

import android.content.Context
import android.os.Build
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Forward10
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.outlined.Laptop
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.TabletAndroid
import androidx.compose.material.icons.outlined.Tv
import androidx.compose.material.icons.outlined.TvOff
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.ui.text.TextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import xyz.vibestream.app.AppState
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.ApiException
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.PlayInfo
import xyz.vibestream.app.api.PlayRequest
import java.util.UUID

// Not Chromecast: every app streams from the server, so casting tells another app what to play and this one
// becomes its remote. This app is also a receiver: hello, inbox long poll, play commands.

@Serializable
data class CastPlaying(
    @SerialName("play_id") val playID: String,
    @SerialName("media_id") val mediaID: Int? = null,
    val title: String,
    val detail: String? = null,
    val position: Double = 0.0,
    val duration: Double = 0.0,
    val paused: Boolean = false,
    val presentation: PlayInfo.Presentation? = null,
    val subtitles: List<PlayInfo.SubtitleTrack>? = null,
    val audio: List<PlayInfo.AudioTrack>? = null,
    @SerialName("subtitle_id") val subtitleID: String? = null,
    @SerialName("audio_index") val audioIndex: Int? = null,
    @SerialName("subtitle_size") val subtitleSize: String? = null,
    @SerialName("subtitle_style") val subtitleStyle: String? = null,
)

@Serializable
data class CastDevice(
    val id: String,
    val name: String,
    @SerialName("own_name") val ownName: String? = null,
    val kind: String,
    @SerialName("profile_id") val profileID: Int? = null,
    val playing: CastPlaying? = null,
) {
    val icon: ImageVector
        get() = when (kind) {
            "tv" -> Icons.Outlined.Tv
            "tablet" -> Icons.Outlined.TabletAndroid
            "phone" -> Icons.Outlined.PhoneAndroid
            else -> Icons.Outlined.Laptop
        }
}

@Serializable
data class CastCommand(
    val type: String,
    @SerialName("play_id") val playID: String? = null,
    val title: String? = null,
    val position: Double? = null,
    val delta: Double? = null,
    @SerialName("profile_id") val profileID: Int? = null,
    val sender: String? = null,
    @SerialName("sender_id") val senderID: String? = null,
    @SerialName("subtitle_id") val subtitleID: String? = null,
    @SerialName("audio_index") val audioIndex: Int? = null,
    @SerialName("subtitle_size") val subtitleSize: String? = null,
    @SerialName("subtitle_style") val subtitleStyle: String? = null,
)

@Serializable private data class Inbox(val commands: List<CastCommand> = emptyList())
@Serializable private data class DeviceList(val devices: List<CastDevice> = emptyList())
@Serializable private data class HelloAnswer(
    val token: String? = null,
    @SerialName("profile_id") val profileID: Int? = null,
    @SerialName("pin_required") val pinRequired: Boolean = false,
)

object Cast {
    lateinit var id: String
        private set
    val name: String = Build.MODEL ?: "Android"
    private var kind = "phone"

    var onPlay: ((CastCommand) -> Unit)? = null

    private var loop: Job? = null
    private var greeted = false
    private val controls = mutableMapOf<String, (CastCommand) -> Unit>()
    private var lastState: CastPlaying? = null
    private var reportedOnce = false

    // Secret bound to this device id by the first hello; sent back as X-Cast-Token on every request.
    private var token: String? = null
    private lateinit var store: android.content.SharedPreferences

    fun init(context: Context) {
        store = context.getSharedPreferences("vibestream", Context.MODE_PRIVATE)
        id = store.getString("vibestream.castID", null) ?: newID()
        token = store.getString("vibestream.castToken", null)
        kind = if (context.resources.configuration.smallestScreenWidthDp >= 600) "tablet" else "phone"
    }

    private fun newID(): String = ("android-" + UUID.randomUUID().toString()).also {
        store.edit().putString("vibestream.castID", it).remove("vibestream.castToken").apply()
    }

    private fun signed(): Map<String, String> = token?.let { mapOf("X-Cast-Token" to it) } ?: emptyMap()

    private var listening = false
    private var listeningAs: Int? = null
    private var foreground = false

    /** Only while the app is in front: a player cannot open from the background. */
    fun start(profile: Int?) {
        listening = true
        listeningAs = profile
        greeted = false
        listen()
    }

    fun setForeground(on: Boolean) {
        foreground = on
        if (on) {
            if (listening) listen()
            if (elsewhereWanted) watchElsewhere()
            target?.let { follow(it, initial = false) }
        } else {
            loop?.cancel(); loop = null
            elsewhereLoop?.cancel(); elsewhereLoop = null
            watch?.cancel(); watch = null
        }
    }

    private fun listen() {
        loop?.cancel()
        loop = null
        if (!foreground) return
        loop = AppState.launch {
            while (isActive) {
                try {
                    if (!greeted) { hello(); greeted = true }
                    val inbox = Api.json.decodeFromString(Inbox.serializer(),
                        Api.castRaw("inbox", mapOf("id" to id, "wait" to "25"), headers = signed()))
                    inbox.commands.forEach(::handle)
                } catch (e: ApiException) {
                    if (e.code == 404 || e.code == 403) greeted = false else delay(5_000)
                } catch (e: kotlinx.coroutines.CancellationException) {
                    throw e
                } catch (_: Exception) {
                    delay(5_000)
                }
            }
        }
    }

    private suspend fun hello() {
        val pin = AppState.profilePin?.takeIf { listeningAs != null && listeningAs == AppState.profile?.id }
        val body = { buildJsonObject {
            put("id", id); put("name", name); put("kind", kind)
            listeningAs?.let { put("profile_id", it) }
        } }
        val headers = signed() + (pin?.let { mapOf("X-Profile-Pin" to it) } ?: emptyMap())
        val text = try {
            Api.castRaw("hello", method = "POST", body = body(), headers = headers)
        } catch (e: ApiException) {
            if (pin != null && (e.code == 429 || e.code == 403 && e.message.contains("pin", ignoreCase = true))) {
                AppState.profilePin = null
                throw e
            }
            // Any other 403: the id is bound to a token this app lost, so start over as a new device.
            if (e.code != 403) throw e
            id = newID()
            token = null
            Api.castRaw("hello", method = "POST", body = body(), headers = pin?.let { mapOf("X-Profile-Pin" to it) } ?: emptyMap())
        }
        val answer = Api.json.decodeFromString(HelloAnswer.serializer(), text)
        answer.token?.takeIf { it != token }?.let {
            token = it
            store.edit().putString("vibestream.castToken", it).apply()
        }
        if (answer.profileID != null && pin != null) AppState.profilePin = null
    }

    private fun handle(command: CastCommand) {
        if (command.type == "play") onPlay?.invoke(command) else controls.values.forEach { it(command) }
    }

    fun onControl(handler: (CastCommand) -> Unit): String = UUID.randomUUID().toString().also { controls[it] = handler }
    fun removeControl(token: String) { controls.remove(token) }

    fun report(playing: CastPlaying?) {
        if (!greeted || (reportedOnce && lastState == playing)) return
        lastState = playing
        reportedOnce = true
        val body = buildJsonObject {
            put("id", id)
            put("playing", playing?.let { Api.json.encodeToJsonElement(CastPlaying.serializer(), it) } ?: JsonNull)
        }
        AppState.launch { runCatching { Api.castRaw("state", method = "POST", body = body, headers = signed()) } }
    }

    suspend fun devices(): List<CastDevice> = runCatching {
        Api.json.decodeFromString(DeviceList.serializer(), Api.castRaw("devices", mapOf("exclude" to id), headers = signed())).devices
    }.getOrDefault(emptyList())

    suspend fun send(command: CastCommand, device: CastDevice): Boolean = runCatching {
        val stamped = command.copy(sender = command.sender ?: name, senderID = id)
        Api.castRaw("devices/${device.id}/command", method = "POST",
            body = Api.json.encodeToJsonElement(CastCommand.serializer(), stamped).jsonObject, headers = signed())
        true
    }.getOrDefault(false)

    suspend fun rename(deviceID: String, to: String): Boolean = runCatching {
        Api.castRaw("devices/$deviceID/name", method = "PUT", body = buildJsonObject { put("name", to) })
        if (deviceID == id) myName = to.ifEmpty { name }
        true
    }.getOrDefault(false)

    var myName by mutableStateOf<String?>(null)
        private set

    var elsewhere by mutableStateOf<List<CastDevice>>(emptyList())
        private set
    private var elsewhereLoop: Job? = null
    private var elsewhereWanted = false

    fun watchElsewhere() {
        elsewhereWanted = true
        if (elsewhereLoop != null || !foreground) return
        elsewhereLoop = AppState.launch {
            while (isActive) {
                val playing = devices().filter { it.playing != null }
                if (playing != elsewhere) elsewhere = playing
                runCatching { Api.json.decodeFromString(CastDevice.serializer(), Api.castRaw("devices/$id", mapOf("sender_id" to id), headers = signed())) }
                    .getOrNull()?.let { myName = it.name }
                delay(5_000)
            }
        }
    }

    var target by mutableStateOf<CastDevice?>(null)
        private set
    var state by mutableStateOf<CastPlaying?>(null)
        private set
    var remoteShown by mutableStateOf(false)
    private var watch: Job? = null

    fun follow(remoteFor: CastDevice) {
        target = remoteFor
        state = remoteFor.playing
        follow(remoteFor, initial = true)
        remoteShown = true
    }

    suspend fun play(request: PlayRequest, at: Double?, device: CastDevice, profile: Int?): Boolean {
        val ok = send(CastCommand("play", playID = request.playID, title = request.title, position = at, profileID = profile), device)
        if (!ok) return false
        target = device
        state = null
        follow(device, initial = true)
        AppState.launch { delay(800); if (target?.id == device.id) remoteShown = true }
        return true
    }

    private fun follow(device: CastDevice, initial: Boolean) {
        watch?.cancel()
        watch = null
        if (!foreground) return
        watch = AppState.launch {
            // Grace period for the other app to open its player before "nothing playing" means it stopped.
            val started = System.currentTimeMillis()
            var seen = false
            while (isActive) {
                try {
                    val now = Api.json.decodeFromString(CastDevice.serializer(), Api.castRaw("devices/${device.id}", mapOf("sender_id" to id), headers = signed()))
                    state = now.playing
                    if (now.playing != null) seen = true
                    if (now.playing == null && (seen || System.currentTimeMillis() - started > 20_000)) { end(); return@launch }
                } catch (e: ApiException) {
                    if (e.code == 404) { end(); return@launch }
                } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (_: Exception) {}
                delay(1_000)
            }
        }
    }

    fun control(command: CastCommand) {
        val device = target ?: return
        state?.let { s ->
            state = when (command.type) {
                "pause" -> s.copy(paused = true)
                "resume" -> s.copy(paused = false)
                "seek" -> s.copy(position = command.position ?: s.position)
                "skip" -> s.copy(position = (s.position + (command.delta ?: 0.0)).coerceIn(0.0, s.duration))
                "subtitle" -> s.copy(subtitleID = if (command.subtitleID == "off") null else command.subtitleID)
                "audio" -> s.copy(audioIndex = command.audioIndex)
                else -> s
            }
        }
        AppState.launch { send(command, device) }
    }

    fun playThere(playID: String, title: String, profile: Int?) {
        val device = target ?: return
        AppState.launch { send(CastCommand("play", playID = playID, title = title, profileID = profile), device) }
    }

    fun stop() { control(CastCommand("stop")); end() }

    private fun end() {
        watch?.cancel()
        target = null
        state = null
        remoteShown = false
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CastPicker(onChoose: (CastDevice) -> Unit) {
    var devices by remember { mutableStateOf<List<CastDevice>?>(null) }
    var renaming by remember { mutableStateOf<CastDevice?>(null) }
    var renamingSelf by remember { mutableStateOf(false) }
    LaunchedEffect(renaming, renamingSelf) { while (true) { devices = Cast.devices(); delay(3_000) } }

    Column(Modifier.fillMaxWidth().padding(bottom = 30.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text("Play on", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White, modifier = Modifier.padding(bottom = 12.dp))
        val list = devices
        when {
            list == null -> Box(Modifier.padding(top = 40.dp)) { BootSpinner(32.dp, 3.dp) }
            list.isEmpty() -> Column(Modifier.padding(top = 30.dp, start = 30.dp, end = 30.dp), horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Icon(Icons.Outlined.TvOff, null, tint = Palette.faint, modifier = Modifier.size(34.dp))
                Text("Nothing to play on", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                Text("Open VibeStream on the TV or another device, and it will show up here.", fontSize = 15.sp,
                    color = Palette.dim, textAlign = TextAlign.Center)
            }
            else -> {
                Column(Modifier.padding(horizontal = 18.dp).fillMaxWidth().background(Color.White.copy(alpha = 0.06f), RoundedCornerShape(16.dp))) {
                    list.forEach { device ->
                        Row(Modifier.fillMaxWidth().combinedClickable(onClick = { onChoose(device) }, onLongClick = { renaming = device })
                            .padding(horizontal = 16.dp, vertical = 15.dp), verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            Icon(device.icon, null, tint = Color.White, modifier = Modifier.size(24.dp))
                            Column(Modifier.weight(1f)) {
                                Text(device.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                                val sub = device.playing?.let { "Playing ${it.title}" } ?: device.ownName?.takeIf { it != device.name }
                                sub?.let { Text(it, fontSize = 13.sp, color = Palette.dim, maxLines = 1) }
                            }
                            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Palette.faint)
                        }
                    }
                }
                Text("Touch and hold a device to rename it.", fontSize = 13.sp, color = Palette.faint, modifier = Modifier.padding(top = 10.dp))
            }
        }
        Row(Modifier.padding(start = 18.dp, end = 18.dp, top = 26.dp).fillMaxWidth().background(Color.White.copy(alpha = 0.06f), RoundedCornerShape(16.dp))
            .padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("This ${Cast.name}", fontSize = 13.sp, color = Palette.faint)
                Text(Cast.myName ?: Cast.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
            }
            Text("Rename", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Palette.accent, modifier = Modifier.pressable { renamingSelf = true })
        }
    }
    renaming?.let { device -> RenamePrompt(device.id, device.name, device.ownName) { renaming = null } }
    if (renamingSelf) RenamePrompt(Cast.id, Cast.myName ?: Cast.name, Cast.name) { renamingSelf = false }
}

/** A sheet rather than a dialog, so the app's keyboard can sit under it. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RenamePrompt(id: String, current: String, own: String?, onDone: () -> Unit) {
    var draft by remember { mutableStateOf(if (current == own) "" else current) }
    val save = { AppState.launch { Cast.rename(id, draft) }; onDone() }
    ModalBottomSheet(onDismissRequest = onDone, containerColor = Palette.ground, sheetState = rememberModalBottomSheetState(true)) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("Cancel", fontSize = 17.sp, color = Color.White, modifier = Modifier.pressable(onClick = onDone))
                Text("Name This Device", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                    textAlign = TextAlign.Center, modifier = Modifier.weight(1f))
                Text("Save", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                    modifier = Modifier.pressable(onClick = save))
            }
            Text(own?.let { "Every device will show this name. Leave it empty to go back to \"$it\"." } ?: "Every device will show this name.",
                fontSize = 14.sp, color = Palette.dim)
            KeyText(draft, own ?: "Name", true, TextStyle(color = Color.White, fontSize = 18.sp),
                Modifier.fillMaxWidth().background(Palette.fill, RoundedCornerShape(14.dp)).padding(14.dp))
        }
        AppKeyboard(
            onType = { draft += it },
            onDelete = { draft = draft.dropLast(1) },
            action = "Save",
            onAction = save,
            capitalise = true,
            atWordStart = draft.isEmpty() || draft.endsWith(" "),
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PlayingElsewhereRow(width: Dp) {
    if (Cast.elsewhere.isEmpty()) return
    var renaming by remember { mutableStateOf<CastDevice?>(null) }
    var menuFor by remember { mutableStateOf<String?>(null) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Playing on Other Devices", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Color.White,
            modifier = Modifier.padding(horizontal = 16.dp))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp), contentPadding = PaddingValues(horizontal = 16.dp)) {
            items(Cast.elsewhere, key = { it.id }) { device ->
                Box {
                    ElsewhereCard(device, width, Modifier.combinedClickable(onClick = { Cast.follow(device) }, onLongClick = { menuFor = device.id }))
                    DropdownMenu(menuFor == device.id, onDismissRequest = { menuFor = null }, containerColor = Color(0xFF242424)) {
                        DropdownMenuItem(text = { Text("Control") }, onClick = { menuFor = null; Cast.follow(device) })
                        DropdownMenuItem(text = { Text("Rename ${device.name}") }, onClick = { menuFor = null; renaming = device })
                        DropdownMenuItem(text = { Text("Stop Playing", color = Color(0xFFFF5A6E)) },
                            onClick = { menuFor = null; AppState.launch { Cast.send(CastCommand("stop"), device) } })
                    }
                }
            }
        }
    }
    renaming?.let { RenamePrompt(it.id, it.name, it.ownName) { renaming = null } }
}

@Composable
private fun ElsewhereCard(device: CastDevice, width: Dp, modifier: Modifier) {
    val playing = device.playing
    var card by remember { mutableStateOf<Card?>(null) }
    LaunchedEffect(playing?.mediaID) { playing?.mediaID?.let { id -> if (card?.mediaID != id) card = runCatching { Api.media(id) }.getOrNull() } }
    val progress = playing?.let { if (it.duration > 0) (it.position / it.duration * 100) else 0.0 } ?: 0.0
    Column(modifier.width(width).clip(RoundedCornerShape(8.dp))) {
        Box(Modifier.width(width).aspectRatio(16f / 9f)) {
            RemoteImage(card?.backdrop ?: card?.poster, Modifier.fillMaxSize())
            Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.55f), Color.Transparent, Color.Black.copy(alpha = 0.8f)))))
            Row(Modifier.padding(8.dp).height(26.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape).padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(device.icon, null, tint = Color.White, modifier = Modifier.size(14.dp))
                Text(device.name, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color.White, maxLines = 1)
            }
            Row(Modifier.align(Alignment.BottomStart).fillMaxWidth().padding(horizontal = 10.dp, vertical = 8.dp), verticalAlignment = Alignment.Bottom) {
                Column(Modifier.weight(1f)) {
                    Text(playing?.title.orEmpty(), fontSize = 15.sp, fontWeight = FontWeight.Bold, color = Color.White, maxLines = 1)
                    (playing?.presentation?.episodeLine ?: playing?.detail)?.let { Text(it, fontSize = 12.sp, color = Color.White.copy(alpha = 0.8f), maxLines = 1) }
                }
                Icon(if (playing?.paused == true) Icons.Filled.Pause else Icons.Filled.GraphicEq, null, tint = Palette.accent, modifier = Modifier.size(16.dp))
            }
        }
        ProgressLine(progress, Modifier.width(width), track = 0.28f)
    }
}

@Composable
fun CastBar() {
    val target = Cast.target ?: return
    val state = Cast.state
    Row(Modifier.widthIn(max = 420.dp).fillMaxWidth().padding(horizontal = 18.dp)
        .shadow(14.dp, CircleShape).background(Color(0xFF1F1F1F), CircleShape).border(1.dp, Color.White.copy(alpha = 0.09f), CircleShape)
        .pressable { Cast.remoteShown = true }.padding(start = 16.dp, end = 8.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Icon(target.icon, null, tint = Palette.good, modifier = Modifier.size(20.dp))
        Column(Modifier.weight(1f)) {
            Text(state?.title ?: "Starting…", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White, maxLines = 1)
            Text("Playing on ${target.name}", fontSize = 12.sp, color = Palette.dim, maxLines = 1)
        }
        val paused = state?.paused ?: false
        Box(Modifier.size(40.dp).pressable(state != null) { Cast.control(CastCommand(if (paused) "resume" else "pause")) }, contentAlignment = Alignment.Center) {
            Icon(if (paused) Icons.Filled.PlayArrow else Icons.Filled.Pause, null, tint = Color.White)
        }
    }
}

@Composable
fun CastRemote(onClose: () -> Unit, onTitle: (Card) -> Unit) {
    val state = Cast.state
    var card by remember { mutableStateOf<Card?>(null) }
    LaunchedEffect(state?.mediaID) { state?.mediaID?.let { id -> if (card?.mediaID != id) card = runCatching { Api.media(id) }.getOrNull() } }
    LaunchedEffect(Cast.target) { if (Cast.target == null) onClose() }
    Column(Modifier.fillMaxWidth().background(Palette.ground)) {
        Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f)) {
            RemoteImage(card?.backdrop ?: card?.poster, Modifier.fillMaxSize())
            Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.7f), Color.Black.copy(alpha = 0.35f), Color.Black.copy(alpha = 0.75f)))))
            Row(Modifier.fillMaxWidth().padding(start = 4.dp, end = 12.dp, top = 6.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.size(44.dp).pressable(onClick = onClose), contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.KeyboardArrowDown, "Hide remote", tint = Color.White)
                }
                Cast.target?.let { t ->
                    Icon(t.icon, null, tint = Palette.good, modifier = Modifier.size(16.dp))
                    Text("Playing on ${t.name}", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Palette.good, maxLines = 1,
                        modifier = Modifier.weight(1f))
                } ?: Spacer(Modifier.weight(1f))
                Text("Stop", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
                    modifier = Modifier.height(32.dp).background(Color.White.copy(alpha = 0.18f), CircleShape)
                        .pressable { Cast.stop(); onClose() }.padding(horizontal = 14.dp, vertical = 6.dp))
            }
            Row(Modifier.align(Alignment.Center), horizontalArrangement = Arrangement.spacedBy(46.dp), verticalAlignment = Alignment.CenterVertically) {
                val paused = state?.paused ?: false
                Icon(Icons.Filled.Replay10, "Back 10 seconds", tint = Color.White, modifier = Modifier.size(30.dp).pressable(state != null) { Cast.control(CastCommand("skip", delta = -10.0)) })
                Icon(if (paused) Icons.Filled.PlayArrow else Icons.Filled.Pause, null, tint = Color.White,
                    modifier = Modifier.size(44.dp).pressable(state != null) { Cast.control(CastCommand(if (paused) "resume" else "pause")) })
                Icon(Icons.Filled.Forward10, "Forward 10 seconds", tint = Color.White, modifier = Modifier.size(30.dp).pressable(state != null) { Cast.control(CastCommand("skip", delta = 10.0)) })
            }
            RemoteScrubber(state, Modifier.align(Alignment.BottomCenter).padding(horizontal = 16.dp, vertical = 10.dp))
        }
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(state?.presentation?.title ?: state?.title ?: "Starting…", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White)
            state?.presentation?.episodeLine?.let { Text(it, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Color.White) }
            (state?.presentation?.overview ?: card?.overview)?.let { Text(it, fontSize = 15.sp, color = Palette.dim, maxLines = 4) }
            card?.let { c -> TitleAbout(c, heading = false) { } }
        }
    }
}

@Composable
private fun RemoteScrubber(state: CastPlaying?, modifier: Modifier) {
    var width by remember { mutableStateOf(1) }
    var dragging by remember { mutableStateOf<Double?>(null) }
    val duration = maxOf(state?.duration ?: 0.0, 1.0)
    val shown = dragging ?: state?.position ?: 0.0
    val fraction = (shown / duration).coerceIn(0.0, 1.0).toFloat()
    val density = LocalDensity.current
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(Modifier.weight(1f).height(26.dp).onSizeChanged { width = it.width }.pointerInput(state != null) {
            detectHorizontalDragGestures(onDragEnd = { dragging?.let { Cast.control(CastCommand("seek", position = it)) }; dragging = null }) { change, _ ->
                if (state != null) dragging = (change.position.x / width).coerceIn(0f, 1f) * duration
            }
        }, contentAlignment = Alignment.CenterStart) {
            Box(Modifier.fillMaxWidth().height(4.dp).background(Color.White.copy(alpha = 0.3f), CircleShape))
            Box(Modifier.fillMaxWidth(fraction).height(4.dp).background(Palette.accent, CircleShape))
            val knob = if (dragging != null) 18.dp else 13.dp
            Box(Modifier.offset { IntOffset((fraction * width - with(density) { knob.toPx() } / 2).toInt(), 0) }.size(knob).background(Palette.accent, CircleShape))
        }
        Text(timecode((duration - shown).coerceAtLeast(0.0)), fontSize = 13.sp, color = Color.White)
    }
}
