# 09 - Catalogue and Selection

**Purpose:** the material catalogue (data file, validation, derived compatibility), the catalogue endpoints, design variants, per-component material selections, and the Materials screen.
**Depends on:** `01-data-model.md`, `02-api-contracts.md`, `03-frontend-foundation.md`, `08-region-editor.md`.
**Endpoints owned (from `02`):** #17 `GET /api/catalogue`, #18 `GET /api/catalogue/materials`, #19-#22 variants, #23-#24 selections.
**Enables:** `10` (redesign inputs), `11` (quantities and rates), `12` (report content).

---

## 0. Implementation-order note (dependency on spec 08)

Specs `07` and `08` already depend on catalogue lookups: `supported` on every component, and compatibility checks when a component's type changes. Those lookups are defined here (section 4) but `00` lists `08` before `09`. This is a known forward reference, not a circular dependency, because the data flow is one-way: the catalogue is read-only reference data.

**Recommended build order:** implement sections 2 to 5 (catalogue file, loader, validation, `catalogue_service` interface, the two catalogue endpoints) **before** finishing `08`. Until then `08` can use a stub that treats `wall`, `pillar`, `balcony`, `railing`, `parapet`, `gate` and `roof_edge` as supported. Sections 6 onward (variants, selections, screen) follow after.

## 1. Scope

In scope: catalogue content and format, startup validation, compatibility, variants, selections, selection validation, Materials screen.
Out of scope: AI material recommendations (postponed, `00`), pricing calculations (`11`), image generation (`10`), user-editable catalogues, per-project custom materials.

## 2. Catalogue file

Location: `CATALOGUE_PATH` (`04`), default `backend/app/data/catalogue.json`. Loaded once at startup, immutable, held in memory (`04` section 12).

### 2.1 File structure

```json
{
  "version": "1",
  "categories": [ { "id": "paint", "name": "Paint" } ],
  "materials": [ { "...Material fields per 02 section 3.4..." } ]
}
```

There is **no `type_map` in the file**. It is derived at load from each material's `compatible_types`, so compatibility is authored in exactly one place. There is no currency field: all rates are in the configured `CURRENCY` (`04`).

### 2.2 Material fields (names are those of `02` section 3.4)

| Field | Type | Rule |
|-------|------|------|
| `id` | string | Unique slug `^[a-z0-9_]{3,60}$` |
| `name` | string | 3-60 characters, display name |
| `category` | string | Must exist in `categories` |
| `compatible_types` | array of `component_type` | Non-empty; values from the vocabulary (`01` section 3.1) excluding `other` |
| `pricing_unit` | `"sqft"` or `"rft"` | Unit that rates and quantities are expressed in |
| `purchase_unit` | string or null | e.g. `litre`, `kg`, `piece`, `panel`. Null when buying is by `pricing_unit` itself |
| `coverage_per_purchase_unit` | number or null | How many `pricing_unit` one purchase unit covers (e.g. 90 sq ft per litre). Both this and `purchase_unit` are set or both null. If set, > 0 |
| `default_material_rate` | number | >= 0, currency per `pricing_unit` of installed material |
| `default_labour_rate` | number | >= 0, currency per `pricing_unit` of installed area/length |
| `default_wastage_pct` | number | 0-50 |
| `swatch_hex` | string | `#RRGGBB` |
| `prompt_description` | string | 5-200 characters. Plain visual description used in the redesign prompt (`10`). No instructions, no quotes or angle brackets. |
| `maintenance_note` | string | 0-200 characters. Shown in the UI and report |
| `durability_note` | string | 0-200 characters. Shown in the UI and report |

Coverage semantics: `coverage_per_purchase_unit` is the amount of installed surface (or length) one purchase unit provides **for the specified system** (e.g. paint: coverage for the standard two-coat system, tiles: the area of one tile, panels: the area of one panel). It is used only to derive an informational purchase quantity (`11`); it does not drive cost.

### 2.3 Categories

| id | name |
|----|------|
| `paint` | Paint |
| `texture` | Texture finish |
| `stone_cladding` | Stone cladding |
| `tiles` | Tiles |
| `panels` | Panels |
| `wood_finish` | Wood finish |
| `glass_railing` | Glass railing |
| `metal_railing` | Metal railing |

Order in this table is the display order and the order used for category totals (`11`).

### 2.4 Starter materials (18)

All rates are **placeholder values in INR** to be replaced by the team with local figures; the UI and report state that default rates are placeholders. Compatible types abbreviated: W wall, P pillar, B balcony, PA parapet, G gate, R roof_edge, RL railing.

| id | name | category | types | unit | purchase unit | coverage | material rate | labour rate | wastage % | swatch |
|----|------|----------|-------|------|---------------|----------|---------------|-------------|-----------|--------|
| `paint_emulsion_matte` | Matte exterior emulsion | paint | W, P, B, PA, R | sqft | litre | 90 | 14 | 10 | 5 | `#E8DCC8` |
| `paint_weatherproof_satin` | Weatherproof satin paint | paint | W, P, B, PA, R | sqft | litre | 80 | 20 | 10 | 5 | `#D9CBB5` |
| `paint_enamel_gate` | Enamel paint for metal | paint | G | sqft | litre | 100 | 22 | 15 | 8 | `#2F2F2F` |
| `texture_sand` | Sand texture finish | texture | W, P, B, PA | sqft | kg | 12 | 38 | 22 | 8 | `#CDBFA8` |
| `texture_rustic` | Rustic roller texture | texture | W, P, PA | sqft | kg | 15 | 30 | 20 | 8 | `#B9A68A` |
| `stone_slate` | Natural slate cladding | stone_cladding | W, P, PA | sqft | none | none | 140 | 70 | 12 | `#6B6F73` |
| `stone_sandstone` | Sandstone cladding | stone_cladding | W, P, PA | sqft | none | none | 120 | 65 | 12 | `#C9A27A` |
| `tile_elevation_clay` | Clay elevation tile | tiles | W, B, PA, R | sqft | piece | 0.75 | 85 | 45 | 10 | `#B5651D` |
| `tile_ceramic_wall` | Ceramic exterior wall tile | tiles | W, B, PA | sqft | piece | 2 | 70 | 40 | 8 | `#D8D2C8` |
| `tile_roof_edge` | Roof edge tile | tiles | R | sqft | piece | 0.5 | 90 | 50 | 10 | `#8C4A2F` |
| `panel_acp` | Aluminium composite panel | panels | W, PA, R | sqft | panel | 32 | 150 | 60 | 10 | `#3E4C59` |
| `panel_hpl_wood` | Wood-look HPL panel | panels | W, R | sqft | panel | 32 | 210 | 70 | 10 | `#8B5E3C` |
| `wood_polish_teak` | Teak-tone wood polish | wood_finish | P, G | sqft | litre | 60 | 55 | 35 | 6 | `#8B5A2B` |
| `wood_wpc_cladding` | Wood-plastic composite cladding | wood_finish | P, G | sqft | none | none | 160 | 60 | 10 | `#7A5230` |
| `glass_clear_toughened` | Clear toughened glass railing | glass_railing | RL | rft | none | none | 2600 | 400 | 3 | `#CFE6EA` |
| `metal_ms_powdercoat` | Powder-coated mild steel railing | metal_railing | RL | rft | none | none | 650 | 200 | 4 | `#2B2B2B` |
| `metal_ss_304` | Stainless steel railing | metal_railing | RL | rft | none | none | 1500 | 300 | 3 | `#B8BCC2` |
| `metal_aluminium` | Aluminium railing | metal_railing | RL | rft | none | none | 900 | 250 | 3 | `#9AA3AB` |

`prompt_description`, `maintenance_note` and `durability_note` are authored per material when the file is created, for example for `glass_clear_toughened`: prompt description "clear toughened glass panels with slim steel fixings", maintenance "Wipe clean every few weeks; check fittings yearly", durability "Very durable; toughened glass is impact resistant". Each description names the **visual appearance** (colour, texture, pattern) of the finished surface so the image model can reproduce it.

**Resulting compatibility (derived):** wall: paint x2, texture x2, stone x2, tiles x2 (`tile_elevation_clay`, `tile_ceramic_wall`), panels x2. Pillar: paint x2, texture x2, stone x2, wood x2. Balcony: paint x2, texture (`texture_sand`), tiles x2. Parapet: paint x2, texture x2, stone x2, tiles x2, `panel_acp`. Gate: `paint_enamel_gate`, wood x2. Roof edge: paint x2, `tile_elevation_clay`, `tile_roof_edge`, panels x2. Railing: glass, metal x3. `window`, `door`, `other`: no materials, so never supported.

### 2.5 Startup validation (`04` section 3, step 5)

Any failure stops startup with a message naming the file and the offending entry.

1. Valid JSON; `version`, `categories`, `materials` present.
2. Category IDs unique; material IDs unique and match the slug pattern.
3. Every material field satisfies the rules in 2.2.
4. Every `category` exists.
5. **Unit consistency rule:** for each component type, all materials compatible with it have the **same `pricing_unit`**. (This determines the measurement mode for a component type, `11` section 3.)
6. At least one material exists for each of `wall`, `pillar`, `railing`.
7. `categories` with no material produce a warning, not an error.

## 3. Catalogue service interface (`catalogue_service.py`, in-memory)

Conceptual functions used by other specs:

| Function | Returns | Used by |
|----------|---------|---------|
| `get_catalogue()` | The full catalogue object with derived `type_map` | endpoint #17 |
| `get_material(material_id)` | Material or none | selections, `10`, `11`, `12` |
| `materials_for_type(component_type)` | Materials in file order | endpoint #18, Materials screen |
| `is_supported_type(component_type)` | true if `materials_for_type` is non-empty | `supported` flag (`08`) |
| `is_compatible(material_id, component_type)` | boolean | selections, `08` type changes |
| `pricing_unit_for_type(component_type)` | `sqft`, `rft` or none | `11` |
| `allows_color(material)` | true when `material.category` is `paint` or `texture` | selection validation |
| `category_order()` | List of category IDs in display order | `11`, `12` |

All functions are pure reads of the in-memory catalogue.

## 4. Catalogue endpoints

Shapes are in `02` sections 3.4 and 5.6.

**GET `/api/catalogue`** returns `{ version, categories, materials, type_map }`. `type_map` maps every type that has at least one material to the list of material IDs (file order). Types without materials are omitted. Response header `Cache-Control: public, max-age=300`.

**GET `/api/catalogue/materials?component_type=wall`**
- `component_type` optional. If omitted, returns all materials.
- Unknown type value: `422 VALIDATION_ERROR` (`fields: [{field: "component_type", problem: "unknown component type"}]`).
- Known type with no materials (`window`): `200` with `{ "items": [] }`.

## 5. Variants

A variant is a named set of selections (`01` section 4.6). A project always has at least one.

| Rule | Detail |
|------|--------|
| Name | 1-60 characters trimmed; unique within the project, **case-insensitive** (checked in the service; the database constraint is the backstop) |
| Limit | Maximum 10 variants per project (`MAX_VARIANTS_PER_PROJECT`, code constant). The 11th returns `409 CONFLICT`, `details.reason = "variant_limit"` |
| Default name | If `name` is omitted on create, the service uses `Design {n}` with the smallest unused `n` (the request shape in `02` requires `name`; the frontend always sends one, this is a server-side fallback) |
| Ordering | `created_at` ascending |
| `is_active` | Derived from `projects.active_variant_id` |

### 5.1 Endpoint behaviour

| Endpoint | Behaviour |
|----------|-----------|
| GET `.../variants` | `{ "items": [Variant] }`, each with its `selections` array (`02` section 3.5), ordered by component `created_at` |
| POST `.../variants` | Body `{ "name", "copy_from_variant_id"? }`. If `copy_from_variant_id` is given it must belong to the project (else `404`); its selections are copied to the new variant (same components, materials and params). Generations, approvals and reports are **never** copied. The new variant does **not** become active automatically. Returns `201`. Duplicate name: `409 CONFLICT` (`duplicate_name`). |
| PATCH `.../variants/{vid}` | Body `{ "name" }`. Same validation. Returns `200`. Touches `updated_at`. |
| DELETE `.../variants/{vid}` | If it is the project's only variant: `409 CONFLICT` (`last_variant`). Otherwise: collect the image files of its generations; delete the variant (cascade removes selections and generations); delete the collected files; if it was active, set `active_variant_id` to the oldest remaining variant. Reports referencing it are kept (`variant_id` becomes null, `01` section 4.11). Returns `204`. |
| Switching the active variant | Done with `PATCH /api/projects/{id}` (`active_variant_id`), owned by `06`. This spec only requires that the value belongs to the project. |

All variant writes touch the project's `updated_at`.

## 6. Selections

A selection links one component to one material within one variant (`01` section 4.7).

### 6.1 PUT `.../variants/{vid}/selections/{cid}` (upsert)

Request: `{ "material_id": "...", "params": { "color_hex"?: "#C8B8A0", "note"?: "..." } }` (`params` optional, default `{}`).

Validation order:

| # | Check | Failure |
|---|-------|---------|
| 1 | Project, variant (belongs to project), component (belongs to project) exist | `404 NOT_FOUND` |
| 2 | `material_id` exists in the catalogue | `422 MATERIAL_INCOMPATIBLE` (message "This material is not available.") |
| 3 | `is_compatible(material_id, component.type)` | `422 MATERIAL_INCOMPATIBLE` (message "{Material} cannot be used on a {type label}.") |
| 4 | `params` contains only the keys `color_hex` and `note` | `422 VALIDATION_ERROR` |
| 5 | `color_hex` matches `#RRGGBB` (stored upper-case) **and** the material allows colour (`allows_color`) | `422 VALIDATION_ERROR` (problem "colour can only be set for paint and texture finishes") |
| 6 | `note` is at most 100 characters; control characters removed; stored trimmed | `422 VALIDATION_ERROR` |

Behaviour: if a selection exists for (variant, component) it is replaced; otherwise created. Stored `params_json` is the canonical JSON of the validated params (keys sorted, empty values omitted). Returns `200` with the Selection object (`02` section 3.5: `component_id`, `material_id`, `params`, `updated_at`). Touches the variant's and project's `updated_at`.

The service does not require the component to be on any particular photo; it only requires `supported` (compatibility already implies this).

### 6.2 DELETE `.../selections/{cid}`

Returns `204`; `404` if the variant has no selection for that component.

### 6.3 Effects of selection changes

| Change | Effect |
|--------|--------|
| Create, replace or delete a selection | Generations of that variant become outdated (fingerprint, `01` section 7.2; computed, no write). Estimates change immediately on next read (`11`). |
| Component type change or deletion (`08`) | Handled by `08`; incompatible selections are removed there |
| Variant duplicate | Selections copied; nothing else |

## 7. Materials screen (`materials.js`)

### 7.1 Data loaded on entering the screen

`components`, `variants` (with selections), `catalogue` (cached), `project`, client config. If there is no photo or no component, show the prerequisite panel (`03` section 5).

### 7.2 Layout

```
+------------------------------------------+-----------------------------+
| Design: [ Design 1  v ] [New][Duplicate] |  Regions (customisable)     |
|         [Rename][Delete]                 |  list: label, type, chip    |
+------------------------------------------+  showing chosen material    |
|                                          +-----------------------------+
|  photo with boxes (customisable regions  |  Materials for "left wall"  |
|  clickable; others dimmed)               |  [category filter chips]    |
|  boxes tinted with the chosen swatch     |  material cards             |
|                                          |  colour picker, note        |
|                                          |  [Clear choice]             |
+------------------------------------------+-----------------------------+
| [Back: Components]                           [Next: Generate redesign] |
+------------------------------------------------------------------------+
```

### 7.3 Behaviour

| Element | Behaviour |
|---------|-----------|
| Variant bar | Dropdown of variants (name and selection count). Choosing one calls `PATCH project { active_variant_id }` and reloads data. **New** asks for a name (default "Design {n}") and creates an empty variant, then activates it. **Duplicate** asks for a name (default "{current} copy"), creates with `copy_from_variant_id`, then activates. **Rename** inline. **Delete** confirms ("This removes the design and its generated images."); disabled with a hint when it is the only variant. |
| Region list | Shows only components with `supported: true` for the **current photo**, ordered as the Components screen. Each row: label, type, and a chip with the chosen material name and swatch, or "No material chosen". |
| Photo overlay | Uses the shared image stage (`03` section 9). Supported regions are clickable; unsupported regions are drawn dimmed with a dashed outline and the tooltip "Not customisable". A region with a selection shows a translucent fill of the material's swatch colour (or the chosen `color_hex`). |
| Selecting a region | Click on the photo or the list. The right panel shows its materials from `materials_for_type` (catalogue data, loaded once; no per-click request). |
| Material card | Swatch, name, category, "Maintenance" and "Durability" notes in an expandable area, and the unit ("per sq ft" or "per running ft"). The chosen card is highlighted. Clicking a card calls PUT immediately. |
| Category filter | Chips for categories present among the region's materials; "All" by default |
| Colour | For materials where colour is allowed (category `paint` or `texture`): a colour input pre-set to the swatch, with a "Use custom colour" checkbox. When checked the chosen `color_hex` is sent in `params`; unchecked sends no `color_hex`. |
| Note | Optional text (max 100) saved on blur: "e.g. darker shade near the entrance". |
| Clear choice | DELETE selection |
| Apply to all | Button **Apply this choice to all {type label} regions** appears once a region has a selection. It sends one PUT per other supported region of the same type in the active variant, sequentially, with a progress hint; failures are reported in one toast. There is no bulk endpoint. |
| Counts | "{k} of {n} customisable regions have a material" |
| Outdated hint | If the active variant has a succeeded generation that is now stale, show "Your redesign is outdated. Generate it again on the next step." |

**Next: Generate redesign** is always enabled (`03` section 10); the Redesign screen shows its own prerequisite panel when there are no selections.

### 7.4 Errors

| Case | Handling |
|------|----------|
| `MATERIAL_INCOMPATIBLE` | Toast with the server message; the region's materials list reloads (this should only happen if the type changed in another tab) |
| `409 CONFLICT` duplicate variant name | Inline message under the name field |
| `409 CONFLICT` variant limit | Toast; **New** and **Duplicate** disabled |
| `404` for a variant or component | Toast "This item no longer exists"; data reloaded |
| Network errors | Shared handling (`03`) |

## 8. Validation summary

| Input | Rule |
|-------|------|
| Variant name | 1-60 chars, unique case-insensitively in the project |
| `material_id` | Exists and is compatible with the component's type |
| `params.color_hex` | `#RRGGBB`, allowed only for paint and texture categories |
| `params.note` | <= 100 chars |
| Variants per project | <= 10 |

## 9. Dependency notes

- **`02` section 3.4** fixes the Material field names. This spec adds no fields. Colour permission is derived from `category`, not a new field.
- **`02` section 3.9 / `11`:** the unit-consistency rule (2.5, rule 5) means a component type's measurement mode is derivable (`11` section 3.1).
- **`08` forward reference:** see section 0.

## 10. Acceptance criteria

- Startup fails with a clear message for each of: duplicate material ID, unknown category, `pricing_unit` mixed within one component type, `coverage_per_purchase_unit` set without `purchase_unit`, invalid `swatch_hex`.
- `GET /api/catalogue` returns the derived `type_map`; `window`, `door` and `other` are absent from it; `GET /api/catalogue/materials?component_type=railing` returns only railing materials; `?component_type=foo` returns `422`.
- `supported` is true for walls and false for windows in `GET /components` (`08`).
- Creating a project yields a variant `Design 1` (from `06`); creating `design 1` again returns `409 duplicate_name`.
- Duplicating a variant copies selections and not generations.
- PUT with an incompatible material (glass railing on a wall) returns `422 MATERIAL_INCOMPATIBLE`; PUT with `color_hex` on a stone material returns `422 VALIDATION_ERROR`; PUT twice with different materials leaves exactly one selection.
- Deleting the last variant returns `409 last_variant`; deleting the active variant activates the oldest remaining one; its generation files are removed from disk.
- A second tab cannot create an 11th variant.
- The Materials screen shows only customisable regions as selectable, tints boxes with the chosen swatch, and **Apply to all** sets the same material on every region of that type.
- Maintenance and durability notes are visible in the UI for every starter material.

## 11. Automated test cases

| # | Test | Expected |
|---|------|----------|
| 1 | Load the starter catalogue | Loads 18 materials and 8 categories; derived `type_map` has exactly the keys wall, pillar, balcony, parapet, gate, roof_edge, railing |
| 2 | Catalogue with duplicate material IDs | Loader raises startup error naming the ID |
| 3 | Catalogue with `wall` materials of mixed units | Startup error (rule 5) |
| 4 | `is_compatible("glass_clear_toughened", "wall")` | false |
| 5 | `allows_color` for `paint_emulsion_matte`, `stone_slate` | true, false |
| 6 | PUT selection with compatible material | 200; one row |
| 7 | PUT selection for a `window` component | 422 `MATERIAL_INCOMPATIBLE` |
| 8 | PUT selection with unknown param key | 422 `VALIDATION_ERROR` |
| 9 | PUT selection, component of another project | 404 |
| 10 | Variant create duplicate name differing only by case | 409 `duplicate_name` |
| 11 | Create 11th variant | 409 `variant_limit` |
| 12 | Delete only variant | 409 `last_variant` |
| 13 | Delete active variant with two others | 204; active is oldest remaining |
| 14 | Duplicate variant | New variant has equal selections, zero generations |
| 15 | Type change via `08` from wall to window with paint selection | Selection removed (cross-spec test) |
