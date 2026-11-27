package app.starfire.webapp

object FileChooserResult {
    fun pickedUris(clipUris: List<String>, dataUri: String?): List<String> =
        clipUris.ifEmpty { listOfNotNull(dataUri) }
}
