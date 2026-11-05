# Current changes — Open Wallpaper

- Category folders are populated from Gallery `/api/external/collections` response field `categories`, mapping each collection key to an array of accessible category names. Category selection calls `/api/external/media` with both `collection` and `category`. Gallery API implementation and deployment are outside this repository.
- Align the scene and playlist media pickers with the local media library's search, type filter, sort, and select-visible controls. Scene selection adds media as layers; playlist selection includes media in the saved playlist.
