package app.starfire.webapp

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView

class SetupActivity : Activity() {
    private lateinit var store: AddressStore
    private lateinit var addressField: EditText
    private lateinit var extraHostsField: EditText
    private lateinit var errorText: TextView
    private lateinit var progress: ProgressBar
    private lateinit var saveButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = AddressStore(this)
        setContentView(buildLayout())
        addressField.setText(store.url().orEmpty())
        extraHostsField.setText(store.extraHosts().joinToString(", "))
    }

    private fun buildLayout(): View {
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val padding = dp(PADDING_DP)
            setPadding(padding, padding * 2, padding, padding)
        }
        column.addView(label(getString(R.string.setup_title, getString(R.string.app_name)), TITLE_SIZE_SP))
        column.addView(label(getString(R.string.setup_intro), BODY_SIZE_SP))
        column.addView(label(getString(R.string.setup_address_label), BODY_SIZE_SP))
        addressField = field(BuildConfig.EXAMPLE_URL, InputType.TYPE_TEXT_VARIATION_URI)
        column.addView(addressField)
        column.addView(label(getString(R.string.setup_extra_hosts_label), BODY_SIZE_SP))
        extraHostsField = field(getString(R.string.setup_extra_hosts_hint), InputType.TYPE_TEXT_VARIATION_URI)
        column.addView(extraHostsField)
        errorText = label("", BODY_SIZE_SP).apply { setTextColor(ERROR_COLOR) }
        column.addView(errorText)
        progress = ProgressBar(this).apply { visibility = View.GONE }
        column.addView(progress)
        saveButton = Button(this).apply {
            text = getString(R.string.setup_save)
            setOnClickListener { submit() }
        }
        column.addView(saveButton)
        if (store.url() != null) column.addView(cancelButton())
        return ScrollView(this).apply { addView(column) }
    }

    private fun cancelButton() = Button(this).apply {
        text = getString(R.string.setup_cancel)
        setOnClickListener { finish() }
    }

    private fun label(text: String, sizeSp: Float) = TextView(this).apply {
        this.text = text
        textSize = sizeSp
        setTextColor(TEXT_COLOR)
        setPadding(0, dp(PADDING_DP / 2), 0, dp(PADDING_DP / 4))
    }

    private fun field(hint: String, inputType: Int) = EditText(this).apply {
        this.hint = hint
        this.inputType = inputType
        isSingleLine = true
        imeOptions = EditorInfo.IME_ACTION_DONE
        setTextColor(TEXT_COLOR)
        setHintTextColor(HINT_COLOR)
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    }

    private fun submit() {
        val address = AddressValidator.validate(addressField.text.toString())
        if (address is AddressResult.Invalid) return showError(getString(problemMessage(address.problem)))
        val extras = AddressValidator.parseExtraHosts(extraHostsField.text.toString())
        if (extras is ExtraHostsResult.Invalid) {
            return showError(getString(R.string.problem_extra_host, extras.entry, getString(problemMessage(extras.problem))))
        }
        address as AddressResult.Valid
        extras as ExtraHostsResult.Valid
        checkReachable(address.url, extras.hosts)
    }

    private fun checkReachable(url: String, extraHosts: List<String>) {
        setBusy(true)
        Thread {
            val outcome = Reachability.check(url)
            runOnUiThread { if (!isFinishing && !isDestroyed) onChecked(outcome, url, extraHosts) }
        }.start()
    }

    private fun onChecked(outcome: Reachability, url: String, extraHosts: List<String>) {
        setBusy(false)
        if (outcome != Reachability.REACHABLE) return showError(getString(unreachableMessage(outcome)))
        store.save(url, extraHosts)
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        finish()
    }

    private fun setBusy(busy: Boolean) {
        progress.visibility = if (busy) View.VISIBLE else View.GONE
        saveButton.isEnabled = !busy
        errorText.text = if (busy) getString(R.string.setup_checking) else ""
    }

    private fun showError(message: String) {
        errorText.text = message
    }

    private fun problemMessage(problem: AddressProblem) = when (problem) {
        AddressProblem.EMPTY -> R.string.problem_empty
        AddressProblem.NOT_A_URL -> R.string.problem_not_a_url
        AddressProblem.NOT_HTTPS -> R.string.problem_not_https
        AddressProblem.NO_HOST -> R.string.problem_no_host
        AddressProblem.HAS_CREDENTIALS -> R.string.problem_has_credentials
        AddressProblem.BAD_HOST -> R.string.problem_bad_host
    }

    private fun unreachableMessage(outcome: Reachability) = when (outcome) {
        Reachability.UNKNOWN_HOST -> R.string.unreachable_unknown_host
        Reachability.TLS_PROBLEM -> R.string.unreachable_tls
        Reachability.TIMEOUT -> R.string.unreachable_timeout
        else -> R.string.unreachable_other
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private companion object {
        const val PADDING_DP = 20
        const val TITLE_SIZE_SP = 22f
        const val BODY_SIZE_SP = 15f
        const val TEXT_COLOR = 0xFFE8E8EC.toInt()
        const val HINT_COLOR = 0xFF8A8A92.toInt()
        const val ERROR_COLOR = 0xFFFF8A80.toInt()
    }
}
