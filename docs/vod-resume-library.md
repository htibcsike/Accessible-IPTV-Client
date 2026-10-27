# VOD progress library and stable identities

The built-in player now offers **View > Continue Watching**, a bounded, keyboard-operated progress list. Entries show title, saved position, local last-watched time and availability. Resume/Enter resolves the selected item against current sources before asking Resume / Play from Beginning / Cancel. Check Availability does not start a media connection. Delete removes one entry; Clear All requires a default-No confirmation. Removing an actively playing entry suppresses checkpointing until the next launch, without stopping playback or deleting provider content or recordings.

## Identity and migration

`vod.xtream_movie_items` preserves the provider movie ID. Resolved series episodes carry episode ID and series ID; M3U inline episodes are explicitly marked as playable VOD. `playback_resume.item_key` hashes a versioned Xtream locator containing a hash of the configured source identity, content type, ID and (for episodes) series. Tokens, hostnames, URL extensions and title changes do not change that stable identity. Accounts, movies and episodes are separate namespaces. Positive bounded numeric IDs are accepted; malformed/missing IDs fall back to an exact URL hash. This does not claim to detect providers reusing an ID for a different film.

Plain M3U has no assumed global content identifier. Its exact URL is scoped to its playlist where available. Titles are never identity keys. Multiple conflicting current matches refuse playback rather than selecting an arbitrary stream. Identical duplicate catalogue entries can resolve to the same stream.

Legacy progress remains valid. On an exact old URL/account match, `lookup` migrates an Xtream record to the new key without mutating its input. If both keys exist, the most recently saved record wins. Cancel does not commit the migration. Already-rotated legacy URLs cannot be reconstructed. Unscoped legacy M3U records are retained instead of assigned to one of potentially several playlists. Legacy episode progress may require opening that episode in its original series; the library does not crawl every provider series.

## Playback ownership and persistence

Preparation saves the outgoing player's progress, then asks for consent *before* activating a subtitle session, changing player visibility or assigning the new channel. Cancel/close/Escape leave the current session running and retain progress. Accepted state is staged, consumed at `play`, and not confused with the old native clock. Session-stop checkpointing cannot resurrect an intentionally cleared or migrated record during this handoff. Metadata is bounded/whitelisted; bookmarks contain hashes, limited locator IDs, timestamps and safe title text, not stream URLs/passwords. Like existing bookmarks, titles are viewing history and are included in the encrypted settings backup.

A modal question pumps the event loop. Preparation re-reads current config before saving so another item's timer checkpoint is not overwritten with an older snapshot. Persistence failures restore the previous in-memory dictionary. Unknown duration and failed seek retain existing progress; existing near-start/near-end thresholds and the 200-item bound remain.

`modal_guard.show_modal` extends the existing notification guard to custom dialogs. Both the library and its confirmation/choice dialogs defer unrelated recording/update message boxes, avoiding nested wxMSW parent-disable problems. The guard unwinds on exceptions and only flushes when the outermost dialog exits.

## Background checking and unavailable content

The UI snapshots sources and progress; workers never read wx/config. Xtream movies use the current movie catalogue and URL builder. Episodes fetch only their recorded series. M3U uses current loaded playlist entries. No saved stream URL is replayed, and checks do not launch media. Catalogue/API errors are reported separately from unavailable/ambiguous content. A playlist load generation change rejects the pending launch and requests reopening the list. Closed/destroyed dialog generations ignore late worker replies. History is never automatically deleted after a failed check.

The list covers configured sources independently of the main playlist filter. Progress restoration remains built-in-player-only; external-player/cast selection yields an explanation rather than changing user preferences or implying unsupported seeking. API availability is not a guarantee that subsequent playback will succeed.

## Localization and acceptance

New UI strings are included in the extraction sources and all 13 translated application catalogues, with compiled MO files. Existing translations are retained. Hungarian user help describes the actual boundaries; the English reference help and other guide sync markers are unchanged. No audit rules, CI exclusions or release gates are relaxed.

Automated validation and exact counts are recorded in the accompanying validation report after the final run. Tests exercise changing URLs, account/type/series separation, malformed IDs, legacy migration, ambiguous/missing/network-failed resolution, current M3U episodes, canceled launch ownership, nested modal guards, active-history deletion and late callbacks. Linux GUI-free tests do not establish native Windows/JAWS/NVDA, frozen-build or real-provider acceptance. Before release, manually check native list navigation/column announcements, wrapping buttons at enlarged text sizes, default-No and Escape behavior, closing while checking, provider reload during checking, real VLC seek behavior and playback/recording notifications while the dialogs are open.
