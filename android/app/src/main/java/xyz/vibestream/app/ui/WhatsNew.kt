package xyz.vibestream.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import xyz.vibestream.app.api.WhatsNew

/** What is new since this device last said, once after an update: a few
 *  lines for whoever is watching, from the server's release notes. */
@Composable
fun WhatsNewSheet(news: WhatsNew, onDone: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp).padding(bottom = 30.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Text("New in ${news.version}", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White)
        Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            news.releases.flatMap { it.items }.forEach { item ->
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Box(Modifier.padding(top = 8.dp).size(7.dp).background(Palette.accent, CircleShape))
                    Text(buildAnnotatedString {
                        withStyle(SpanStyle(color = Color.White, fontWeight = FontWeight.SemiBold)) { append(item.title) }
                        append(item.text)
                    }, fontSize = 15.sp, color = Palette.dim)
                }
            }
        }
        Pill(true, Modifier.fillMaxWidth(), onClick = onDone) { PillLabel("Got it") }
    }
}
