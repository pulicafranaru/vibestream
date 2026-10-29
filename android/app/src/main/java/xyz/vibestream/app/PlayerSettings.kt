package xyz.vibestream.app

import android.view.HapticFeedbackConstants
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.VolumeUp
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.outlined.BugReport
import androidx.compose.material.icons.outlined.ClosedCaption
import androidx.compose.material.icons.outlined.FormatSize
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import xyz.vibestream.app.ui.Palette
import xyz.vibestream.app.ui.pressable

// The sideways player's settings, beside the picture (iOS PlayerSettings). The picture goes on
// playing in a box on the left; this is the column of pills on the right.
@Composable
internal fun PlayerSettings(
    model: PlayerModel,
    statsShown: Boolean,
    onStats: (Boolean) -> Unit,
    onPreviewLook: (Boolean) -> Unit,
    onClose: () -> Unit,
) {
    var page by remember { mutableStateOf(Debug.string("settingsPage") ?: "root") }
    var forward by remember { mutableStateOf(true) }
    val view = LocalView.current
    fun go(next: String, ahead: Boolean = true) { forward = ahead; page = next }
    fun tick() { view.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK) }
    LaunchedEffect(page) { onPreviewLook(page == "appearance") }
    DisposableEffect(Unit) { onDispose { onPreviewLook(false) } }

    val info = model.info
    val subtitleLabel = info?.subtitles?.firstOrNull { it.id == model.subtitleID }?.label ?: "Off"
    val audioLabel = info?.audio?.firstOrNull { it.index == model.currentAudio }?.label ?: "Default"

    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (page != "root") Bare(Icons.AutoMirrored.Filled.KeyboardArrowLeft, "Back") { go("root", ahead = false) }
            Text(title(page), fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White, maxLines = 1,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f).padding(start = if (page == "root") 4.dp else 0.dp))
            Bare(Icons.Filled.Close, "Close settings", onClick = onClose)
        }
        AnimatedContent(page, transitionSpec = {
            slideInHorizontally { if (forward) it / 3 else -it / 3 } + fadeIn() togetherWith fadeOut()
        }, label = "page") { shown ->
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                when (shown) {
                    "subtitles" -> {
                        Choice("Off", model.subtitleID == null) { model.chooseSubtitle(null); tick() }
                        info?.subtitles?.forEach { track ->
                            Choice(track.label, track.id == model.subtitleID) { model.chooseSubtitle(track.id); tick() }
                        }
                    }
                    "appearance" -> {
                        // The sample line drawn the chosen way, here and on the
                        // picture beside, where it is seen against the film.
                        Box(Modifier.fillMaxWidth().heightIn(min = 64.dp)
                            .background(Brush.verticalGradient(listOf(Color(0xFF474747), Color(0xFF1F1F1F))), RoundedCornerShape(16.dp))
                            .padding(12.dp), contentAlignment = Alignment.Center) {
                            SubtitleSample(SAMPLE_CAPTION, model.subtitleSize, model.subtitleStyle, base = SubtitleLook.base(380f))
                        }
                        SectionLabel("Size")
                        Pills(SubtitleLook.sizes, model.subtitleSize) { model.setLook(size = it); tick() }
                        SectionLabel("Style")
                        Pills(SubtitleLook.styles, model.subtitleStyle) { model.setLook(style = it); tick() }
                    }
                    "audio" -> info?.audio?.forEach { track ->
                        Choice(track.label, track.index == model.currentAudio) { model.chooseAudio(track.index); tick() }
                    }
                    "debug" -> {
                        SectionLabel("Playback stats")
                        Choice("Off", !statsShown) { onStats(false); tick() }
                        Choice("On", statsShown) { onStats(true); tick() }
                    }
                    else -> {
                        Entry(Icons.Outlined.ClosedCaption, "Subtitles", subtitleLabel) { go("subtitles") }
                        Entry(Icons.Outlined.FormatSize, "Subtitle Appearance", SubtitleLook.label(model.subtitleSize, model.subtitleStyle)) { go("appearance") }
                        Entry(Icons.AutoMirrored.Outlined.VolumeUp, "Audio", audioLabel) { go("audio") }
                        Entry(Icons.Outlined.BugReport, "Debug", if (statsShown) "On" else "Off") { go("debug") }
                    }
                }
            }
        }
    }
}

/** On the film while Subtitle Appearance is open, whether anyone speaks. */
internal const val SAMPLE_CAPTION = "This is how subtitles will look."

private fun title(page: String) = when (page) {
    "subtitles" -> "Subtitles"
    "appearance" -> "Subtitle Appearance"
    "audio" -> "Audio"
    "debug" -> "Debug"
    else -> "Settings"
}

/** Bare glyphs, as the player's own close and lock. */
@Composable
private fun Bare(icon: ImageVector, label: String, onClick: () -> Unit) {
    Box(Modifier.size(44.dp).pressable(onClick = onClick), contentAlignment = Alignment.Center) {
        Icon(icon, label, tint = Color.White, modifier = Modifier.size(24.dp))
    }
}

/** A setting on the first page: its name, what it is set to, a chevron. */
@Composable
private fun Entry(icon: ImageVector, title: String, value: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().background(Palette.chip, CircleShape).pressable(onClick = onClick)
        .padding(horizontal = 18.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Icon(icon, null, tint = Color.White, modifier = Modifier.width(24.dp).size(22.dp))
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Color.White, maxLines = 1)
            Text(value, fontSize = 13.sp, color = Palette.dim, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Palette.dim, modifier = Modifier.size(20.dp))
    }
}

/** One of a page's choices: the one in use is the white pill. */
@Composable
private fun Choice(title: String, chosen: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().background(if (chosen) Color.White else Palette.chip, CircleShape).pressable(onClick = onClick)
        .padding(horizontal = 18.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = if (chosen) Color.Black else Color.White,
            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        if (chosen) Icon(Icons.Filled.Check, null, tint = Color.Black, modifier = Modifier.size(18.dp))
    }
}

/** A short row of choices side by side, wrapping when the column is narrow. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Pills(items: List<Pair<String, String>>, chosen: String, onChoose: (String) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items.forEach { (value, label) ->
            val on = value == chosen
            Text(label, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = if (on) Color.Black else Color.White,
                modifier = Modifier.background(if (on) Color.White else Palette.chip, CircleShape).pressable { onChoose(value) }
                    .padding(horizontal = 16.dp, vertical = 10.dp))
        }
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(text.uppercase(), fontSize = 12.sp, fontWeight = FontWeight.Bold, color = Palette.faint,
        modifier = Modifier.padding(top = 6.dp, start = 4.dp))
}
