package xyz.vibestream.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

@Composable
fun VMark(height: Dp = 40.dp, modifier: Modifier = Modifier) {
    val points = listOf(5f to 0f, 479f to 0f, 809f to 1055f, 1134f to 0f, 1594f to 0f, 1050f to 1466f, 559f to 1466f)
    Canvas(modifier.size(height * 1600f / 1466f, height)) {
        val sx = size.width / 1600f
        val sy = size.height / 1466f
        val path = Path().apply {
            points.forEachIndexed { i, (x, y) -> if (i == 0) moveTo(x * sx, y * sy) else lineTo(x * sx, y * sy) }
            close()
        }
        drawPath(path, Brush.linearGradient(Palette.ember, Offset.Zero, Offset(size.width, size.height)))
    }
}
