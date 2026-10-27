package xyz.vibestream.app

import android.content.Intent

// Debug-only intent extras to reach screens directly, e.g. adb shell am start ... --es tab search
object Debug {
    private var extras: Map<String, String> = emptyMap()

    fun read(intent: Intent?) {
        if (!BuildConfig.DEBUG) return
        val bundle = intent?.extras ?: return
        extras = bundle.keySet().associateWith { bundle.get(it)?.toString().orEmpty() }
    }

    fun has(name: String) = name in extras
    fun string(name: String): String? = extras[name]
    fun int(name: String): Int? = extras[name]?.toIntOrNull()
}
