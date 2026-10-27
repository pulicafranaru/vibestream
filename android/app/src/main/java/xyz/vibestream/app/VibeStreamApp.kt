package xyz.vibestream.app

import android.app.Application
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import xyz.vibestream.app.api.Api

class VibeStreamApp : Application(), SingletonImageLoader.Factory {
    override fun onCreate() {
        super.onCreate()
        Api.init(cacheDir)
        AppState.init(this)
        xyz.vibestream.app.ui.Cast.init(this)
        ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStart(owner: LifecycleOwner) = AppState.setForeground(true)
            override fun onStop(owner: LifecycleOwner) = AppState.setForeground(false)
        })
    }

    override fun newImageLoader(context: PlatformContext): ImageLoader =
        ImageLoader.Builder(context)
            .components { add(OkHttpNetworkFetcherFactory(callFactory = { Api.http })) }
            .build()
}
