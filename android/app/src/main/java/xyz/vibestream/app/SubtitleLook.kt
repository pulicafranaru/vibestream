package xyz.vibestream.app

import android.graphics.Typeface
import android.util.TypedValue
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.CaptionStyleCompat
import androidx.media3.ui.SubtitleView

// How subtitles look: the TV's choices (web/src/shared/tracks.js), three sizes and four styles.
object SubtitleLook {
    /** The yellow the TV uses, #f5d020. */
    val yellow = Color(0xFFF5D020)

    val sizes = listOf("small" to "Small", "medium" to "Medium", "large" to "Large")
    val styles = listOf("shadow" to "Drop Shadow", "outline" to "Outline", "yellow" to "Yellow", "boxed" to "Boxed")

    /** Against the default size, as the TV scales its own. */
    fun scale(size: String) = when (size) { "small" -> 0.75f; "large" -> 1.4f; else -> 1f }

    fun label(size: String, style: String) =
        "${sizes.firstOrNull { it.first == size }?.second ?: "Medium"}, ${styles.firstOrNull { it.first == style }?.second ?: "Drop Shadow"}"

    // The type size for a picture this tall, in dp, before the size chosen, as the TV sizes its lines.
    fun base(pictureHeight: Float) = (pictureHeight * 0.048f).coerceIn(13f, 34f)

    // The look given to ExoPlayer's subtitle view, for a picture `height` dp tall, lifted `lift`.
    @androidx.annotation.OptIn(UnstableApi::class)
    fun apply(view: SubtitleView, size: String, style: String, height: Float, lift: Float) {
        val white = android.graphics.Color.WHITE
        val clear = android.graphics.Color.TRANSPARENT
        val black = android.graphics.Color.BLACK
        val bold = Typeface.DEFAULT_BOLD
        val look = when (style) {
            "outline" -> CaptionStyleCompat(white, clear, clear, CaptionStyleCompat.EDGE_TYPE_OUTLINE, black, bold)
            "yellow" -> CaptionStyleCompat(android.graphics.Color.rgb(0xF5, 0xD0, 0x20), clear, clear, CaptionStyleCompat.EDGE_TYPE_DROP_SHADOW, black, bold)
            "boxed" -> CaptionStyleCompat(white, android.graphics.Color.argb(199, 0, 0, 0), clear, CaptionStyleCompat.EDGE_TYPE_NONE, black, bold)
            else -> CaptionStyleCompat(white, clear, clear, CaptionStyleCompat.EDGE_TYPE_DROP_SHADOW, black, bold)
        }
        view.setApplyEmbeddedStyles(false)
        view.setApplyEmbeddedFontSizes(false)
        view.setStyle(look)
        view.setFixedTextSize(TypedValue.COMPLEX_UNIT_DIP, base(height) * scale(size))
        view.setBottomPaddingFraction(lift)
    }
}

/** A line of text drawn the way subtitles will be, for the samples and the
 *  style swatches. */
@Composable
fun SubtitleSample(text: String, size: String, style: String, base: Float = 17f, modifier: Modifier = Modifier) {
    val fontSize = (base * SubtitleLook.scale(size)).sp
    val colour = if (style == "yellow") SubtitleLook.yellow else Color.White
    when (style) {
        "outline" -> Box(modifier) {
            // The outline under the letters, then the letters over it.
            Text(text, fontSize = fontSize, fontWeight = FontWeight.Bold, color = Color.Black, textAlign = TextAlign.Center,
                style = TextStyle(drawStyle = Stroke(width = 5f)))
            Text(text, fontSize = fontSize, fontWeight = FontWeight.Bold, color = colour, textAlign = TextAlign.Center)
        }
        "boxed" -> Text(text, fontSize = fontSize, fontWeight = FontWeight.Bold, color = colour, textAlign = TextAlign.Center,
            modifier = modifier.background(Color.Black.copy(alpha = 0.78f), RoundedCornerShape(4.dp)).padding(horizontal = 8.dp, vertical = 2.dp))
        else -> Text(text, fontSize = fontSize, fontWeight = FontWeight.Bold, color = colour, textAlign = TextAlign.Center,
            style = TextStyle(shadow = Shadow(Color.Black.copy(alpha = 0.9f), Offset(0f, 3f), 8f)), modifier = modifier)
    }
}
