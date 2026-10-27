package xyz.vibestream.app.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Backspace
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.outlined.ArrowUpward
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Popup
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

// The app's own keyboard; the system one never opens. Each screen draws it, since a sheet is its own window
// and a keyboard at the root would sit behind it.

object OnScreenKeyboard {
    var up by mutableStateOf(false)
}

private val KeyFill = Color(0xFF2C2C2E)
private val FunctionFill = Color(0xFF1B1B1D)
private val Pressed = Color(0xFF4A4A4E)
private val Board = Color(0xFF111111)

private val ACCENTS = mapOf(
    'a' to "ăâàáäå", 'e' to "éèêë", 'i' to "îíìïı", 'o' to "óòôöø", 'u' to "úùûü",
    's' to "șşß", 't' to "țţ", 'c' to "çč", 'n' to "ñ", 'z' to "žż", 'y' to "ÿ",
)

private val LETTERS = listOf("qwertyuiop", "asdfghjkl", "zxcvbnm")
private val SYMBOLS = listOf("1234567890", "-/:;()&@\"", ".,?!'")

@Composable
fun AppKeyboard(
    onType: (String) -> Unit,
    onDelete: () -> Unit,
    action: String? = null,
    onAction: () -> Unit = {},
    digits: Boolean = false,
    capitalise: Boolean = false,
    atWordStart: Boolean = false,
    registerUp: Boolean = false,
) {
    if (registerUp) {
        DisposableEffect(Unit) {
            OnScreenKeyboard.up = true
            onDispose { OnScreenKeyboard.up = false }
        }
    }
    var symbols by remember { mutableStateOf(false) }
    var shift by remember { mutableStateOf(0) }
    val upper = shift != 0 || (capitalise && atWordStart)
    val haptic = LocalHapticFeedback.current
    val type: (String) -> Unit = { s ->
        haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
        onType(s)
        if (shift == 1) shift = 0
    }
    val delete = {
        haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
        onDelete()
    }
    var lastShift by remember { mutableStateOf(0L) }

    Column(
        Modifier.fillMaxWidth().background(Board).navigationBarsPadding().padding(horizontal = 3.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(9.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (digits) {
            listOf("123", "456", "789", " 0<").forEach { row ->
                KeyRow(Modifier.widthIn(max = 420.dp).padding(horizontal = 24.dp)) {
                    row.forEach { c ->
                        when (c) {
                            ' ' -> Spacer(Modifier.weight(1f))
                            '<' -> FunctionKey(Modifier.weight(1f), onPress = delete, repeats = true) { DeleteIcon() }
                            else -> Key(Modifier.weight(1f), onPress = { type("$c") }) {
                                Text("$c", fontSize = 24.sp, color = Color.White)
                            }
                        }
                    }
                }
            }
            return@Column
        }
        val rows = if (symbols) SYMBOLS else LETTERS
        KeyRow { rows[0].forEach { c -> CharKey(c, upper && !symbols, type) } }
        KeyRow(Modifier.padding(horizontal = if (symbols) 0.dp else 17.dp)) {
            rows[1].forEach { c -> CharKey(c, upper && !symbols, type) }
        }
        KeyRow {
            if (symbols) {
                Spacer(Modifier.weight(1.5f))
            } else {
                FunctionKey(Modifier.weight(1.5f), onPress = {
                    val now = System.currentTimeMillis()
                    shift = when {
                        shift != 2 && now - lastShift < 300 -> 2
                        shift == 0 -> 1
                        else -> 0
                    }
                    lastShift = now
                }, lit = shift != 0) {
                    Icon(if (shift != 0) Icons.Filled.ArrowUpward else Icons.Outlined.ArrowUpward, "Shift",
                        tint = if (shift != 0) Color.Black else Color.White, modifier = Modifier.size(20.dp))
                }
            }
            Spacer(Modifier.width(4.dp))
            rows[2].forEach { c -> CharKey(c, upper && !symbols, type) }
            Spacer(Modifier.width(4.dp))
            FunctionKey(Modifier.weight(1.5f), onPress = delete, repeats = true) { DeleteIcon() }
        }
        KeyRow {
            FunctionKey(Modifier.weight(1.6f), onPress = { symbols = !symbols }) {
                Text(if (symbols) "ABC" else "123", fontSize = 15.sp, fontWeight = FontWeight.Medium, color = Color.White)
            }
            Key(Modifier.weight(5f), onPress = { type(" ") }) {
                Text("space", fontSize = 15.sp, color = Palette.dim)
            }
            if (action != null) {
                Key(Modifier.weight(2.2f), fill = Palette.accent, onPress = onAction) {
                    Text(action, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                }
            }
        }
    }
}

@Composable
private fun DeleteIcon() =
    Icon(Icons.AutoMirrored.Outlined.Backspace, "Delete", tint = Color.White, modifier = Modifier.size(20.dp))

@Composable
fun KeyText(
    text: String,
    placeholder: String,
    active: Boolean,
    style: TextStyle,
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    centred: Boolean = false,
) {
    val blink = rememberInfiniteTransition(label = "caret")
    val caret by blink.animateFloat(1f, 0f, infiniteRepeatable(tween(530, delayMillis = 300), RepeatMode.Reverse), label = "caret")
    Row(modifier, verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = if (centred) Arrangement.Center else Arrangement.Start) {
        if (text.isEmpty()) {
            if (active) Caret(style, caret)
            Text(placeholder, style = style.copy(color = Palette.dim), maxLines = 1, overflow = TextOverflow.Ellipsis,
                textAlign = if (centred) TextAlign.Center else TextAlign.Start)
        } else {
            Box(Modifier.weight(1f, fill = false).horizontalScroll(rememberScrollState(), reverseScrolling = true)) {
                Text(text, style = style, maxLines = 1, softWrap = false,
                    modifier = if (selected && active) Modifier.background(Palette.accent.copy(alpha = 0.45f), RoundedCornerShape(3.dp)) else Modifier)
            }
            if (active && !selected) Caret(style, caret)
        }
    }
}

@Composable
private fun Caret(style: TextStyle, alpha: Float) {
    Box(Modifier.padding(horizontal = 1.dp).width(2.dp).height((style.fontSize.value * 1.25f).dp)
        .alpha(alpha).background(Palette.accent, RoundedCornerShape(1.dp)))
}

@Composable
private fun KeyRow(modifier: Modifier = Modifier, content: @Composable RowScope.() -> Unit) {
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(5.dp), content = content)
}

@Composable
private fun RowScope.CharKey(c: Char, upper: Boolean, onType: (String) -> Unit) {
    val shown = if (upper) c.uppercaseChar() else c
    val accents = ACCENTS[c]?.let { if (upper) it.uppercase() else it }
    var choosing by remember { mutableStateOf(false) }
    Box(Modifier.weight(1f)) {
        Key(Modifier.fillMaxWidth(), onPress = { onType("$shown") },
            onLongPress = accents?.let { { choosing = true } }) {
            Text("$shown", fontSize = 22.sp, color = Color.White)
        }
        if (choosing && accents != null) {
            Popup(alignment = Alignment.BottomCenter, offset = IntOffset(0, -150), onDismissRequest = { choosing = false }) {
                Row(Modifier.clip(RoundedCornerShape(10.dp)).background(Color(0xFF3A3A3C)).padding(4.dp),
                    horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    accents.forEach { a ->
                        Box(Modifier.size(width = 38.dp, height = 46.dp).clip(RoundedCornerShape(7.dp))
                            .pressable { onType("$a"); choosing = false }, contentAlignment = Alignment.Center) {
                            Text("$a", fontSize = 22.sp, color = Color.White)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun FunctionKey(
    modifier: Modifier,
    onPress: () -> Unit,
    height: Dp = 46.dp,
    fill: Color = FunctionFill,
    lit: Boolean = false,
    repeats: Boolean = false,
    content: @Composable () -> Unit,
) = Key(modifier, height, if (lit) Color.White else fill, onPress, repeats = repeats, content = content)

@Composable
private fun Key(
    modifier: Modifier,
    height: Dp = 46.dp,
    fill: Color = KeyFill,
    onPress: () -> Unit,
    onLongPress: (() -> Unit)? = null,
    repeats: Boolean = false,
    content: @Composable () -> Unit,
) {
    var down by remember { mutableStateOf(false) }
    val press by rememberUpdatedState(onPress)
    val long by rememberUpdatedState(onLongPress)
    Box(
        modifier.height(height).clip(RoundedCornerShape(8.dp)).background(if (down && fill != Color.White) Pressed else fill)
            .pointerInput(repeats) {
                coroutineScope {
                    val timers = this
                    awaitEachGesture {
                        awaitFirstDown().consume()
                        down = true
                        val job = timers.launch {
                            if (repeats) {
                                press()
                                delay(420)
                                while (true) { press(); delay(55) }
                            } else if (long != null) {
                                delay(380)
                                long?.invoke()
                            }
                        }
                        val up = waitForUpOrCancel()
                        val held = long != null && job.isCompleted
                        job.cancel()
                        down = false
                        if (!repeats && up && !held) press()
                    }
                }
            },
        contentAlignment = Alignment.Center,
    ) { content() }
}

private suspend fun androidx.compose.ui.input.pointer.AwaitPointerEventScope.waitForUpOrCancel(): Boolean {
    while (true) {
        val event = awaitPointerEvent()
        if (event.changes.all { !it.pressed }) return true
        if (event.changes.any { it.isConsumed && it.pressed && it.positionChanged() }) return false
    }
}

private fun androidx.compose.ui.input.pointer.PointerInputChange.positionChanged() = position != previousPosition
