# This is a relational model and is not cannoical. Do not use unless directed" 

# MRP Identity, Artist, Release, and Credit Model

MRP should distinguish between **people**, **public personas**, **artist projects**, **membership**, and **release/track-specific participation**. The current “artist” concept should be treated as an **Artist Project**, not as a person. This keeps the model flexible enough to support solo artists, virtual artists, bands, aliases, featured artists, fictional identities, publishing credits, likeness assets, and track-specific PR details.

## Core Models

### Person

A **Person** represents the underlying individual identity, whether real, fictional, virtual, or internal. This is the layer used when MRP needs real-name attribution, rights metadata, publishing attribution, or continuity behind a public-facing identity.

Primary fields:

* `id`
* `real_name`
* `first_name`
* `last_name`
* `preferred_name`
* `person_type` — real, fictional, virtual, internal, unknown
* `public_visibility` — public, private, internal
* `bio_notes`
* `rights_notes`
* `internal_notes`

Relationships:

* A Person may have one or more Personas.
* A Person may have one or more Likeness Assets.
* A Person may receive Credits directly when real-name attribution is needed.

---

### Persona

A **Persona** represents a public-facing identity, stage name, alias, character, or performance identity. Examples include PCBender, STAB, Flea, Sting, Raven Cortez, or a mythic identity used by Lingua Aeternum.

Primary fields:

* `id`
* `display_name`
* `stage_name`
* `persona_type` — stage_name, alias, character, virtual_performer, public_identity
* `linked_person_id`
* `public_bio`
* `voice_profile`
* `visual_identity_notes`
* `public_visibility`
* `internal_notes`

Relationships:

* A Persona may belong to one Person.
* A Persona may be used as a solo Artist Project.
* A Persona may be a member of a band or collective Artist Project through Membership.
* A Persona may receive release-level or track-level Credits.
* A Persona may have one or more Likeness Assets.

---

### Artist Project

An **Artist Project** is the catalog-facing musical act. This is what releases music and appears on artist pages. It may represent a solo artist, band, duo, collective, virtual artist, fictional artist, label-created project, or alias project.

Primary fields:

* `id`
* `name`
* `display_name`
* `artist_project_type` — solo, band, duo, collective, virtual, fictional, alias, label_project
* `primary_persona_id`
* `public_bio`
* `promoter_bio`
* `short_description`
* `genre_tags`
* `website_slug`
* `dsp_artist_ids`
* `public_visibility`
* `internal_notes`

Relationships:

* An Artist Project may have many Releases.
* An Artist Project may have many Members through Membership.
* An Artist Project may appear as a primary, featured, or supporting participant on Releases or Tracks through Credits.
* An Artist Project may have Likeness Assets, artist images, and promotional assets.

---

### Membership

A **Membership** represents a standing relationship between a Person or Persona and an Artist Project. This is for band members, collectives, recurring virtual performers, or long-term project participants. It should not be used for one-off features.

Primary fields:

* `id`
* `artist_project_id`
* `person_id`
* `persona_id`
* `member_display_name`
* `role`
* `start_date`
* `end_date`
* `status` — current, former, guest_member, inactive
* `display_order`
* `public_visibility`
* `public_bio_blurb`
* `internal_notes`

Relationships:

* Membership connects a Person and/or Persona to an Artist Project.
* Membership defines who belongs to a band or collective.
* Membership does not imply participation on every Release or Track.

---

### Release

A **Release** represents a single, EP, or album. It belongs to one or more Artist Projects and contains one or more Tracks.

Primary fields:

* `id`
* `title`
* `release_type` — single, ep, album
* `primary_artist_project_id`
* `release_date`
* `upc`
* `catalog_id`
* `label`
* `publisher`
* `copyright`
* `genre_tags`
* `style_description`
* `cover_art_asset_id`
* `dsp_links`
* `review_status`
* `publication_status`
* `promoter_status`
* `internal_notes`

Relationships:

* A Release has one or more Tracks.
* A Release has one or more release-level Credits.
* A Release may have featured artists, with-artists, remixers, producers, writers, or other participants through Credits.
* A Release may have artwork, snippets, reviews, DSP links, and promotional copy.

---

### Track

A **Track** represents an individual song or audio work within a Release.

Primary fields:

* `id`
* `release_id`
* `track_number`
* `title`
* `isrc`
* `duration`
* `lyrics`
* `style_description`
* `audio_asset_id`
* `snippet_asset_id`
* `intensity_notes`
* `review_status`
* `publication_status`
* `internal_notes`

Relationships:

* A Track belongs to one Release.
* A Track has one or more track-level Credits.
* A Track may have a 30-second MP3 snippet.
* A Track may have lyrics, reviews, DSP links, and promotional notes.
* A Track may identify specific performers, such as lead vocal, backing vocal, guitar, producer, lyricist, or featured artist.

---

### Credit / Participation

A **Credit** represents a release-specific or track-specific contribution. This is the flexible layer that handles primary artists, featured artists, guests, band-member performances, songwriters, producers, vocalists, remixers, and PR-relevant participation.

Primary fields:

* `id`
* `target_type` — release, track
* `target_id`
* `entity_type` — artist_project, persona, person
* `entity_id`
* `credit_role`
* `billing_role` — primary_artist, featured_artist, with_artist, guest, remixer, producer, songwriter, performer, none
* `instrument_or_function`
* `display_name`
* `display_order`
* `public_visibility`
* `rights_relevant`
* `royalty_share`
* `publishing_share`
* `credit_notes`
* `internal_notes`

Relationships:

* A Credit connects a Person, Persona, or Artist Project to a Release or Track.
* Credits should be used for one-off collaborations and features.
* Credits should also be used for track-specific roles by band members.
* Credits determine “who did what” on a specific Release or Track.
* Credits are separate from Membership.

---

### Likeness Asset

A **Likeness Asset** represents a reusable visual identity reference. It may be used for artist pages, videos, promotional materials, social media, avatars, press kits, or visual continuity.

Primary fields:

* `id`
* `asset_type` — portrait, full_body, promo_photo, video_reference, avatar, press_image, album_era_reference
* `file_path`
* `represents_type` — person, persona, artist_project
* `represents_id`
* `title`
* `description`
* `era`
* `canonical`
* `usage_context`
* `public_visibility`
* `rights_notes`
* `prompt_notes`
* `generation_source`
* `internal_notes`

Relationships:

* A Likeness Asset may belong to a Person, Persona, or Artist Project.
* A Person, Persona, or Artist Project may have many Likeness Assets.
* Likeness Assets support continuity across videos, artwork, artist pages, social posts, and promotional materials.

## Key Rules

1. **Artist Project is the catalog identity.** It is what releases music.
2. **Person is the underlying identity.** It supports rights, real-name attribution, and internal continuity.
3. **Persona is the public identity.** It supports stage names, aliases, characters, and virtual performers.
4. **Membership is long-term belonging.** It defines who is part of a band, duo, collective, or project.
5. **Credit is specific participation.** It defines who contributed to a particular release or track.
6. **Featuring is a Credit, not Membership.** PCBender featuring STAB does not make STAB part of PCBender.
7. **Band membership does not automatically imply track participation.** A member may be in the band but not credited on a specific track.
8. **Credits may point to Artist Projects, Personas, or Persons.** This allows public billing, stage-name use, and real-name rights attribution.
9. **Likeness Assets are identity assets, not just images.** They preserve visual continuity for artists, personas, members, and virtual performers.
10. **Simple artists should stay simple.** The model should allow solo artists to use only Artist Project and Persona fields, while bands and complex virtual projects can expand into Person, Membership, Credit, and Likeness layers as needed.
