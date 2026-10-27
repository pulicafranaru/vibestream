// Generated. Do not edit.
package xyz.vibestream.app.ui

import androidx.compose.ui.graphics.Color
import xyz.vibestream.app.R

data class AvatarColour(val id: String, val top: Color, val bottom: Color)

object AvatarPalette {
    val colours = listOf(
        AvatarColour("crimson", Color(0xFFE8293D), Color(0xFFA31229)),
        AvatarColour("teal", Color(0xFF1F7A8C), Color(0xFF0D3B4A)),
        AvatarColour("amber", Color(0xFFFABF24), Color(0xFFD97805)),
        AvatarColour("emerald", Color(0xFF33D499), Color(0xFF059669)),
        AvatarColour("violet", Color(0xFF8C5CF5), Color(0xFF5926C9)),
        AvatarColour("magenta", Color(0xFFE83099), Color(0xFFB01478)),
        AvatarColour("azure", Color(0xFF2E8FF7), Color(0xFF1259B8)),
        AvatarColour("coral", Color(0xFFF5704F), Color(0xFFC74029)),
        AvatarColour("lime", Color(0xFFA3E636), Color(0xFF66A60D)),
        AvatarColour("slate", Color(0xFF94A3B8), Color(0xFF475469)),
    )
    val faces = listOf("smile", "grin", "wink", "surprised", "content", "cool")

    fun drawable(face: String): Int = when (face) {
        "smile" -> R.drawable.avatar_smile
        "grin" -> R.drawable.avatar_grin
        "wink" -> R.drawable.avatar_wink
        "surprised" -> R.drawable.avatar_surprised
        "content" -> R.drawable.avatar_content
        "cool" -> R.drawable.avatar_cool
        else -> R.drawable.avatar_smile
    }
}
