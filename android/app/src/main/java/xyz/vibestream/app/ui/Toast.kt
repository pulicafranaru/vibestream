package xyz.vibestream.app.ui

import android.app.Activity
import android.graphics.PixelFormat
import android.os.Build
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.setViewTreeLifecycleOwner
import androidx.lifecycle.setViewTreeViewModelStoreOwner
import androidx.savedstate.setViewTreeSavedStateRegistryOwner
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.lang.ref.WeakReference

// A failure, said once, in a sentence, over whatever is on screen.
object Toasts {
    private class Item(val message: String)

    private var current by mutableStateOf<Item?>(null)
    private var activity = WeakReference<ComponentActivity>(null)
    private var view: ComposeView? = null
    private var hiding: Job? = null
    private val scope = MainScope()

    /** The activity in front, set from the app's lifecycle callbacks. */
    fun attach(to: Activity) {
        if (to !is ComponentActivity || activity.get() === to) return
        detach()
        activity = WeakReference(to)
    }

    fun forget(from: Activity) {
        if (activity.get() === from) { detach(); activity = WeakReference(null) }
    }

    fun error(message: String) {
        val host = activity.get() ?: return
        // Added again on every toast, so it goes above a sheet opened since.
        detach()
        val composeView = ComposeView(host).apply {
            setViewTreeLifecycleOwner(host)
            setViewTreeViewModelStoreOwner(host)
            setViewTreeSavedStateRegistryOwner(host)
            setContent { ToastLayer() }
        }
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            // No token: the activity's window manager gives it the activity's.
            gravity = Gravity.TOP
            if (Build.VERSION.SDK_INT >= 28) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }
        runCatching { host.windowManager.addView(composeView, params) }.onFailure { return }
        view = composeView
        current = Item(message)
        composeView.performHapticFeedback(
            if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.REJECT else HapticFeedbackConstants.LONG_PRESS,
        )
        hiding?.cancel()
        hiding = scope.launch {
            delay(4_500)
            dismiss()
        }
    }

    fun dismiss() {
        hiding?.cancel()
        current = null
        // Long enough for the slide out.
        hiding = scope.launch { delay(400); detach() }
    }

    private fun detach() {
        val v = view ?: return
        view = null
        runCatching { activity.get()?.windowManager?.removeViewImmediate(v) }
    }

    @Composable
    private fun ToastLayer() {
        val item = current
        Box(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 16.dp, vertical = 6.dp), contentAlignment = Alignment.TopCenter) {
            AnimatedVisibility(
                item != null,
                enter = slideInVertically { -it } + fadeIn(),
                exit = slideOutVertically { -it } + fadeOut(),
            ) {
                Row(
                    Modifier.widthIn(max = 520.dp).fillMaxWidth()
                        .background(Color(0xF0201A16), RoundedCornerShape(22.dp))
                        .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(22.dp))
                        .pressable { dismiss() }
                        .pointerInput(Unit) {
                            detectVerticalDragGestures { _, drag -> if (drag < -8) dismiss() }
                        }
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    ErrorBadge(26.dp)
                    Text(lastMessage(item), fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                }
            }
        }
    }

    // The message stays drawn while the toast slides away.
    private var shown = ""
    private fun lastMessage(item: Item?): String {
        if (item != null) shown = item.message
        return shown
    }
}

/** What a failure says on screen: the server's own sentence when it gave one. */
fun Throwable.said(): String = message?.takeIf { it.isNotBlank() } ?: "Something went wrong. Try again."

/** A red circle with an exclamation mark: this went wrong. The toast leads
 *  with it, and a button whose last attempt failed wears it on its corner. */
@Composable
fun ErrorBadge(size: Dp = 22.dp, modifier: Modifier = Modifier) {
    Box(
        modifier.size(size).background(Palette.danger, CircleShape).semantics { contentDescription = "Failed" },
        contentAlignment = Alignment.Center,
    ) {
        Text("!", fontSize = (size.value * 0.62f).sp, lineHeight = (size.value * 0.62f).sp,
            fontWeight = FontWeight.Black, color = Color.White)
    }
}
