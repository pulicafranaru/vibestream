package xyz.vibestream.app.ui

import androidx.annotation.OptIn
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.delay
import xyz.vibestream.app.R

@OptIn(UnstableApi::class)
@Composable
fun IntroView(onFinish: () -> Unit) {
    val context = LocalContext.current
    val tall = !isWide()
    var finishing by remember { mutableStateOf(false) }
    val alpha by animateFloatAsState(if (finishing) 0f else 1f, tween(700), label = "intro")
    val player = remember {
        ExoPlayer.Builder(context).build().apply {
            // Ambient audio: does not interrupt music already playing.
            setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MOVIE).build(), false)
            val raw = if (tall) R.raw.intro_portrait else R.raw.intro
            setMediaItem(MediaItem.fromUri("android.resource://${context.packageName}/$raw"))
            prepare()
            playWhenReady = true
        }
    }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) { if (state == Player.STATE_ENDED) finishing = true }
        }
        player.addListener(listener)
        onDispose { player.removeListener(listener); player.release() }
    }
    LaunchedEffect(finishing) {
        if (finishing) { player.pause(); delay(700); onFinish() }
    }
    Box(Modifier.fillMaxSize().alpha(alpha).background(Color.Black).pointerInput(Unit) { detectTapGestures { finishing = true } }) {
        AndroidView({ PlayerView(it).apply {
            useController = false
            this.player = player
            resizeMode = AspectRatioFrameLayout.RESIZE_MODE_ZOOM
            setShutterBackgroundColor(android.graphics.Color.BLACK)
        } }, Modifier.fillMaxSize())
    }
}
