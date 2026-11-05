# Current changes — Open Wallpaper

- Category folders are populated from Gallery `/api/external/collections` response field `categories`, mapping each collection key to an array of accessible category names. Category selection calls `/api/external/media` with both `collection` and `category`. Gallery API implementation and deployment are outside this repository.
- Align the scene and playlist media pickers with the local media library's search, type filter, sort, and select-visible controls. Scene selection adds media as layers; playlist selection includes media in the saved playlist.
- Gallery collection and category branch actions fetch all catalog pages. Playlist branches select current media IDs; scene branches create a playlist and add it as a slideshow layer. Device grants use batches of 500 items because Gallery limits each grant request to 500; the dashboard no longer rejects larger branches.
- Preserve in-progress scene and playlist edits in tab-scoped session storage across unexpected page reloads. Clear the draft on sign-out; the reload cause is not yet established.
