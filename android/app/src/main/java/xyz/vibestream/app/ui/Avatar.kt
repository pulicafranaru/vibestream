package xyz.vibestream.app.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

// Avatar ids like "violet-wink" name a gradient and a face; ids must match the server's AVATAR_COLOURS.
object AvatarArt {
    val colours get() = AvatarPalette.colours
    val faces get() = AvatarPalette.faces

    val all: List<String> get() = colours.flatMap { col -> faces.map { "${col.id}-$it" } }

    fun parts(id: String?): Pair<AvatarColour, String> {
        val pieces = (id ?: "crimson-smile").split("-", limit = 2)
        val colour = colours.firstOrNull { it.id == pieces.first() } ?: colours[0]
        val face = pieces.getOrNull(1)?.takeIf { it in faces } ?: faces[0]
        return colour to face
    }
}

@Composable
fun Avatar(id: String?, size: Dp = 96.dp, modifier: Modifier = Modifier) {
    val (colour, face) = AvatarArt.parts(id)
    Box(modifier.size(size).background(Brush.verticalGradient(listOf(colour.top, colour.bottom)), CircleShape)) {
        Image(painterResource(AvatarPalette.drawable(face)), null, Modifier.fillMaxSize())
    }
}
