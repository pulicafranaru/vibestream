package xyz.vibestream.app.ui

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.outlined.MicNone
import androidx.compose.material.icons.outlined.PlayCircle
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.Brush
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.ui.geometry.Offset
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import xyz.vibestream.app.AppState
import xyz.vibestream.app.Debug
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.api.Card
import xyz.vibestream.app.api.PlayRequest

@Composable
fun SearchView(nav: Navigator, active: Boolean) {
    var term by rememberSaveable { mutableStateOf(Debug.string("search") ?: "") }
    var results by remember { mutableStateOf<List<Card>>(emptyList()) }
    var searching by remember { mutableStateOf(false) }
    var answered by remember { mutableStateOf<String?>(null) }
    var failed by remember { mutableStateOf(false) }
    var retry by remember { mutableStateOf(0) }
    var typing by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val voice = remember { VoiceSearch(context) }
    val wide = isWide()

    LaunchedEffect(active) {
        if (active) { delay(150); typing = true }
        else { typing = false; voice.cancel() }
    }
    BackHandler(typing) { typing = false }
    DisposableEffect(Unit) { onDispose { voice.cancel() } }

    LaunchedEffect(term, retry) {
        val query = term.trim()
        failed = false
        if (query.length < 2) { results = emptyList(); answered = null; return@LaunchedEffect }
        if (retry == 0) delay(280)
        searching = true
        try {
            results = Api.search(query)
            answered = query
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            android.util.Log.w("VibeStream", "search failed", e)
            failed = true
        } finally {
            searching = false
        }
    }

    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) voice.start(hints(), onHeard = { heard -> scope.launch { term = spokenTerm(heard) } })
        else voice.problem = "Voice search needs the microphone. Turn it on for VibeStream in Settings."
    }

    val suggestions = remember(AppState.feed) {
        val seen = HashSet<Int>()
        AppState.rows.filter { it.id != "continue" }.flatMap { it.items }.filter { seen.add(it.mediaID) }.take(30)
    }
    val shown = if (term.isBlank()) suggestions else results
    val fieldHeight = if (wide) 56.dp else 44.dp

    Column(Modifier.fillMaxSize().padding(top = LocalTopClearance.current)) {
        Row(
            Modifier.fillMaxWidth().background(Palette.ground).padding(start = 16.dp, end = 16.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                Modifier.weight(1f).height(fieldHeight).clip(CircleShape).background(Palette.fill)
                    .padding(horizontal = if (wide) 20.dp else 16.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Icon(Icons.Outlined.Search, null, tint = Palette.dim, modifier = Modifier.size(if (wide) 22.dp else 20.dp))
                Box(Modifier.weight(1f)) {
                    if (voice.listening) {
                        Text(voice.heard.ifEmpty { "Listening..." }, fontSize = if (wide) 19.sp else 16.sp,
                            color = if (voice.heard.isEmpty()) Palette.dim else Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    } else {
                        KeyText(term, "Search shows, movies, genres...", typing,
                            TextStyle(color = Color.White, fontSize = if (wide) 19.sp else 16.sp),
                            Modifier.fillMaxWidth().pressable { typing = true })
                    }
                }
                if (searching) BootSpinner(18.dp, 2.dp)
                else if (term.isNotEmpty() && !voice.listening) {
                    Icon(Icons.Filled.Cancel, "Clear", tint = Palette.dim, modifier = Modifier.size(20.dp).pressable { term = "" })
                }
            }
            val pulse = rememberInfiniteTransition(label = "mic")
            val glow by pulse.animateFloat(1f, 0.55f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "glow")
            Box(
                Modifier.size(fieldHeight).clip(CircleShape)
                    .background(if (voice.listening) Color.White else Palette.fill)
                    .pressable {
                        if (voice.listening) voice.stop()
                        else {
                            typing = false
                            if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                                voice.start(hints(), onHeard = { heard -> scope.launch { searching = true; term = spokenTerm(heard); searching = false } })
                            } else permission.launch(Manifest.permission.RECORD_AUDIO)
                        }
                    },
                contentAlignment = Alignment.Center,
            ) {
                Icon(if (voice.listening) Icons.Filled.Mic else Icons.Outlined.MicNone,
                    if (voice.listening) "Stop listening" else "Search by voice",
                    tint = if (voice.listening) Color.Black else Color.White,
                    modifier = Modifier.size(if (wide) 24.dp else 22.dp).alpha(if (voice.listening) glow else 1f))
            }
        }

        val dismiss = remember {
            object : NestedScrollConnection {
                override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                    if (source == NestedScrollSource.UserInput && available.y != 0f) {
                        typing = false
                    }
                    return Offset.Zero
                }
            }
        }
        val list = rememberLazyListState()
        val shade by animateFloatAsState(if (list.canScrollBackward) 1f else 0f, tween(180), label = "shade")
        Box(Modifier.weight(1f).fillMaxWidth()) {
            LazyColumn(
                state = list,
                modifier = Modifier.fillMaxSize().nestedScroll(dismiss).pointerInput(Unit) {
                    detectTapGestures { typing = false }
                },
                verticalArrangement = Arrangement.spacedBy(if (wide) 12.dp else 8.dp),
                contentPadding = PaddingValues(bottom = 24.dp + TabBarClearance),
            ) {
                voice.problem?.let { problem ->
                    item { Text(problem, fontSize = 13.sp, color = Palette.dim, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) }
                }
                item {
                    Text(if (term.isEmpty()) "Recommended TV Shows & Movies" else "Results", fontSize = if (wide) 24.sp else 18.sp,
                        fontWeight = FontWeight.Bold, color = Color.White,
                        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 6.dp, bottom = if (wide) 6.dp else 4.dp))
                }
                items(shown, key = { it.mediaID }) { card -> SearchRow(card, wide, nav) { typing = false } }
                val query = term.trim()
                if (failed && !searching) {
                    item {
                        Column(Modifier.fillMaxWidth().padding(top = 50.dp), horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            Text("Couldn't search right now.", fontSize = 15.sp, color = Palette.dim)
                            Pill(false, Modifier.width(140.dp), onClick = { retry++ }) { PillLabel("Try Again") }
                        }
                    }
                } else if (query.isNotEmpty() && answered == query && results.isEmpty() && !searching) {
                    item {
                        Text("Nothing matched “$query”", fontSize = 15.sp, color = Palette.dim,
                            modifier = Modifier.fillMaxWidth().padding(top = 50.dp), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                    }
                }
            }
            Box(Modifier.fillMaxWidth().height(TopFade).alpha(shade).background(
                Brush.verticalGradient(listOf(Palette.ground.copy(alpha = 0.8f), Color.Transparent))))
        }
        if (typing) {
            AppKeyboard(
                onType = { term += it },
                onDelete = { term = term.dropLast(1) },
                action = "Search",
                onAction = { typing = false },
                registerUp = true,
            )
        }
    }
}

private fun hints(): List<String> = AppState.rows.flatMap { it.items }.map { it.title }.distinct()

private suspend fun spokenTerm(heard: List<String>): String =
    runCatching { Api.spoken(heard) }.getOrNull() ?: heard.firstOrNull().orEmpty()

@Composable
private fun SearchRow(card: Card, wide: Boolean, nav: Navigator, onLeave: () -> Unit) {
    val art = if (wide) 270.dp else 146.dp
    Row(
        Modifier.fillMaxWidth().pressable { onLeave(); nav.open(card) }.padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(if (wide) 20.dp else 12.dp),
    ) {
        RemoteImage(card.backdrop ?: card.poster, Modifier.width(art).height(art * 9 / 16).clip(RoundedCornerShape(4.dp)))
        Text(card.title, fontSize = if (wide) 21.sp else 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White,
            maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        if (card.playableDownloadID != null) {
            Box(Modifier.size(if (wide) 60.dp else 44.dp).pressable {
                onLeave()
                if (card.isSeries && card.resumeDownloadID == null) nav.open(card)
                else card.playableDownloadID?.let { nav.play(PlayRequest(it.toString(), if (card.isSeries) card.resumeTitle else card.title)) }
            }, contentAlignment = Alignment.Center) {
                Icon(Icons.Outlined.PlayCircle, "Play ${card.title}", tint = Color.White, modifier = Modifier.size(if (wide) 44.dp else 34.dp))
            }
        }
    }
}

// Voice search uses only the on-device recogniser (Android 12+) so audio never leaves the phone.
class VoiceSearch(private val context: Context) {
    var listening by mutableStateOf(false)
        private set
    var heard by mutableStateOf("")
        private set
    var problem by mutableStateOf<String?>(null)

    private var recognizer: SpeechRecognizer? = null
    private var readings: List<String> = emptyList()
    private var done: ((List<String>) -> Unit)? = null

    fun start(hints: List<String>, onHeard: (List<String>) -> Unit) {
        if (listening) return
        problem = null
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || !SpeechRecognizer.isOnDeviceRecognitionAvailable(context)) {
            problem = "This phone cannot recognise speech on the device, and voice search does not send your voice anywhere else."
            return
        }
        val r = SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
        recognizer = r
        done = onHeard
        readings = emptyList()
        heard = ""
        listening = true
        r.setRecognitionListener(object : RecognitionListener {
            override fun onPartialResults(partial: Bundle?) {
                val texts = partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty().filter { it.isNotBlank() }
                if (texts.isNotEmpty()) { readings = texts.distinct().take(6); heard = texts.first() }
            }
            override fun onResults(results: Bundle?) {
                val texts = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty().filter { it.isNotBlank() }
                if (texts.isNotEmpty()) readings = texts.distinct().take(6)
                finish()
            }
            override fun onError(error: Int) {
                if (readings.isNotEmpty()) finish() else {
                    teardown()
                    problem = if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS)
                        "Voice search needs the microphone. Turn it on for VibeStream in Settings."
                    else "Didn't catch that. Try again?"
                }
            }
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_WEB_SEARCH)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 6)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1300L)
            if (hints.isNotEmpty() && Build.VERSION.SDK_INT >= 34) {
                putExtra(RecognizerIntent.EXTRA_BIASING_STRINGS, ArrayList(hints.take(100)))
            }
        }
        r.startListening(intent)
    }

    fun stop() {
        if (!listening) return
        recognizer?.stopListening()
    }

    fun cancel() {
        if (!listening) return
        done = null
        teardown()
    }

    private fun finish() {
        if (!listening) return
        val result = readings
        val callback = done
        teardown()
        if (result.isEmpty()) problem = "Didn't catch that. Try again?" else callback?.invoke(result)
    }

    private fun teardown() {
        recognizer?.destroy()
        recognizer = null
        done = null
        listening = false
        heard = ""
    }
}
