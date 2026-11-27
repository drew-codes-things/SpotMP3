package app.starfire.webapp

import android.app.Activity
import android.content.Intent
import android.os.Bundle

class LaunchActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val next = if (AddressStore(this).url() == null) SetupActivity::class.java else MainActivity::class.java
        startActivity(Intent(this, next))
        finish()
    }
}
