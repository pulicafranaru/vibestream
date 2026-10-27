package xyz.vibestream.app.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

object Palette {
    val accent = Color(0xFFFF6A00)
    val ember = listOf(Color(0xFFFFB000), Color(0xFFFF6A00), Color(0xFFFF2E63))
    val good = Color(0xFFFFB000)
    val ground = Color(0xFF0E0A08)
    val dim = Color(0xFFB8B8B8)
    val faint = Color(0xFF7D7D7D)
    val chip = Color(0xFF2A221C)
    val tile = Color(0xFF1E1915)
    val fill = Color(0x24FFFFFF)
}

object Metrics {
    const val posterAspect = 2f / 3f
    val posterWidth = 116.dp
    val posterWidthPad = 152.dp
    val rowSpacing = 10.dp
}

fun timecode(seconds: Double): String {
    if (!seconds.isFinite() || seconds < 0) return "0:00"
    val total = seconds.toInt()
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}

@Composable
fun VibeTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Palette.accent,
            background = Palette.ground,
            surface = Palette.ground,
            onBackground = Color.White,
            onSurface = Color.White,
        ),
        content = content,
    )
}
