package xyz.vibestream.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import xyz.vibestream.app.ui.RootView
import xyz.vibestream.app.ui.VibeTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        Debug.read(intent)
        enableEdgeToEdge(SystemBarStyle.dark(android.graphics.Color.TRANSPARENT), SystemBarStyle.dark(android.graphics.Color.TRANSPARENT))
        super.onCreate(savedInstanceState)
        setContent {
            VibeTheme {
                RootView(onPlay = { request -> startActivity(PlayerActivity.intent(this, request)) })
            }
        }
    }

    // Refresh the rows on resume so Resume Watching reflects other devices.
    override fun onRestart() {
        super.onRestart()
        if (AppState.profile != null && !AppState.loading) lifecycleScope.launch { AppState.loadFeed() }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        Debug.read(intent)
    }
}
