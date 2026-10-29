package xyz.vibestream.app

import android.app.Activity
import android.app.Application
import android.os.Bundle
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import xyz.vibestream.app.api.Api
import xyz.vibestream.app.ui.Toasts

class VibeStreamApp : Application(), SingletonImageLoader.Factory {
    override fun onCreate() {
        super.onCreate()
        Api.init(cacheDir)
        AppState.init(this)
        xyz.vibestream.app.ui.Cast.init(this)
        // Downloads and cast polling run while any screen is up, never behind.
        // Toasts draw over whichever screen is in front.
        registerActivityLifecycleCallbacks(object : ActivityLifecycleCallbacks {
            override fun onActivityResumed(activity: Activity) = Toasts.attach(activity)
            override fun onActivityPaused(activity: Activity) = Toasts.forget(activity)
            override fun onActivityCreated(activity: Activity, state: Bundle?) {}
            override fun onActivityStarted(activity: Activity) {}
            override fun onActivityStopped(activity: Activity) {}
            override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) {}
            override fun onActivityDestroyed(activity: Activity) {}
        })
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
