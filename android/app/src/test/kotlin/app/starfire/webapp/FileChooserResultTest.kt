package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertEquals

class FileChooserResultTest {
    @Test
    fun everyClipItemIsPickedFirst() {
        assertEquals(listOf("content://a/1", "content://a/2", "content://a/3"), FileChooserResult.pickedUris(listOf("content://a/1", "content://a/2", "content://a/3"), "content://a/1"))
    }

    @Test
    fun dataUriIsUsedWhenThereIsNoClip() {
        assertEquals(listOf("content://a/9"), FileChooserResult.pickedUris(emptyList(), "content://a/9"))
    }

    @Test
    fun nothingPickedGivesAnEmptyList() {
        assertEquals(emptyList(), FileChooserResult.pickedUris(emptyList(), null))
    }

    @Test
    fun singleClipItemWithoutDataIsKept() {
        assertEquals(listOf("content://a/1"), FileChooserResult.pickedUris(listOf("content://a/1"), null))
    }
}
