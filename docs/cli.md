# CLI reference

Typed architecture models, coherent releases and standards projections.

**Usage**:

```console
$ architecture [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `doctor`: Report the installed Python stack.
* `validate`: Validate a source model and report what...
* `schema`: Print or write the generated JSON Schema...
* `publish`: Publish a source model as a coherent release.
* `persist`: Stage a release and write its manifest...
* `releases`: List published releases and whether they...
* `show`: Print one release manifest.
* `archive`: Write a self-contained milestone archive.
* `resume`: Finish a publication whose manifest exists...
* `discard`: Remove an orphan manifest.
* `constraints`: Report or apply the declared Delta table...
* `vacuum`: Remove files no retained release needs.
* `recipes`: List the versioned query recipes, or...
* `query`: Run one query recipe against a release.
* `plan`: Show what the engine plans for one recipe.
* `impact`: Bounded, explainable traversal from one...
* `graph`: Structural analyses over one release&#x27;s graph.
* `baseline`: Print the model a release holds.
* `change`: Apply a typed change set to a release and...
* `diff`: Explain what changed between two releases.
* `compare`: Compare a design alternative with the...
* `review`: Record a decision on a change report.
* `output`: Reserved: distribute a release&#x27;s outputs...
* `build`: Reserved: the full projection pipeline is...

## `architecture doctor`

Report the installed Python stack.

**Usage**:

```console
$ architecture doctor [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `architecture validate`

Validate a source model and report what was checked.

**Usage**:

```console
$ architecture validate [OPTIONS] {source}
```

**Arguments**:

* `source`: A YAML model to validate.  [required]

**Options**:

* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture schema`

Print or write the generated JSON Schema contracts.

**Usage**:

```console
$ architecture schema [OPTIONS]
```

**Options**:

* `--family <str>`: Emit one family to stdout.
* `--write`: Write every emittable family to its declared path.
* `--help`: Show this message and exit.

## `architecture publish`

Publish a source model as a coherent release.

**Usage**:

```console
$ architecture publish [OPTIONS] {source}
```

**Arguments**:

* `source`: A YAML model to publish.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--expect-parent <str>`: The release the candidate was built against; pass an empty value for the first.
* `--release-id <str>`: Defaults to the next rel-NNNN in the store.
* `--no-source-snapshot`: Pin only the source revision and digest; do not copy it into the release.
* `--scenario <str>`: Publish as a design alternative under this scenario id.
* `--baseline <str>`: The release this alternative is derived from.
* `--help`: Show this message and exit.

## `architecture persist`

Stage a release and write its manifest without exposing it.

**Usage**:

```console
$ architecture persist [OPTIONS] {source}
```

**Arguments**:

* `source`: A YAML model to stage.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--expect-parent <str>`: The release the candidate was built against; pass an empty value for the first.
* `--release-id <str>`: Defaults to the next rel-NNNN in the store.
* `--scenario <str>`: Publish as a design alternative under this scenario id.
* `--baseline <str>`: The release this alternative is derived from.
* `--help`: Show this message and exit.

## `architecture releases`

List published releases and whether they resolve.

**Usage**:

```console
$ architecture releases [OPTIONS]
```

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--verify`: Read every pinned version back.
* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture show`

Print one release manifest.

**Usage**:

```console
$ architecture show [OPTIONS] {release_id}
```

**Arguments**:

* `release_id`: The release to print.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--help`: Show this message and exit.

## `architecture archive`

Write a self-contained milestone archive.

**Usage**:

```console
$ architecture archive [OPTIONS] {release_id}
```

**Arguments**:

* `release_id`: The release to archive.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--into <path>`: Where to write the archive.
* `--help`: Show this message and exit.

## `architecture resume`

Finish a publication whose manifest exists but never became current.

**Usage**:

```console
$ architecture resume [OPTIONS] {release_id}
```

**Arguments**:

* `release_id`: The persisted release to expose.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--help`: Show this message and exit.

## `architecture discard`

Remove an orphan manifest.

**Usage**:

```console
$ architecture discard [OPTIONS] {release_id}
```

**Arguments**:

* `release_id`: The orphan manifest to remove.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--help`: Show this message and exit.

## `architecture constraints`

Report or apply the declared Delta table constraints.

**Usage**:

```console
$ architecture constraints [OPTIONS]
```

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--apply`: Write the declared constraints.
* `--help`: Show this message and exit.

## `architecture vacuum`

Remove files no retained release needs.

**Usage**:

```console
$ architecture vacuum [OPTIONS]
```

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--apply`: Actually remove the files.
* `--help`: Show this message and exit.

## `architecture recipes`

List the versioned query recipes, or describe one.

**Usage**:

```console
$ architecture recipes [OPTIONS] [recipe_id]
```

**Arguments**:

* `recipe_id`: Describe one recipe.

**Options**:

* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture query`

Run one query recipe against a release.

**Usage**:

```console
$ architecture query [OPTIONS] {recipe_id}
```

**Arguments**:

* `recipe_id`: The recipe to run.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--release <str>`: Defaults to the current release.
* `--base <str>`: The base side of a comparison.
* `--candidate <str>`: The candidate side of a comparison.
* `--param NAME=VALUE`: Bind one declared parameter. Repeatable.
* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture plan`

Show what the engine plans for one recipe.

**Usage**:

```console
$ architecture plan [OPTIONS] {recipe_id}
```

**Arguments**:

* `recipe_id`: The recipe to plan.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--release <str>`: Defaults to the current release.
* `--param NAME=VALUE`: Bind one declared parameter. Repeatable.
* `--help`: Show this message and exit.

## `architecture impact`

Bounded, explainable traversal from one object.

**Usage**:

```console
$ architecture impact [OPTIONS] {element_id}
```

**Arguments**:

* `element_id`: Where the traversal starts.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--release <str>`: Defaults to the current release.
* `--policy <str>`: A named policy; `impact --policy list` shows them. Default impact.structural.
* `--unverified`: Report only dependencies that are not qualified.
* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture graph`

Structural analyses over one release&#x27;s graph.

**Usage**:

```console
$ architecture graph [OPTIONS] {analysis}:<cycles|generations|components|condensation|closure|reduction>
```

**Arguments**:

* `analysis:<cycles|generations|components|condensation|closure|reduction>`: Which structural analysis to run.  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--release <str>`: Defaults to the current release.
* `--policy <str>`: A named policy. Defaults to containment.descendants.  [default: containment.descendants]
* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture baseline`

Print the model a release holds.

**Usage**:

```console
$ architecture baseline [OPTIONS]
```

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--release <str>`: Defaults to the current release.
* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture change`

Apply a typed change set to a release and report what it would do.

**Usage**:

```console
$ architecture change [OPTIONS] {change_set}
```

**Arguments**:

* `change_set`: A JSON change set (CORE-10).  [required]

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--release <str>`: Defaults to the current release.
* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture diff`

Explain what changed between two releases.

**Usage**:

```console
$ architecture diff [OPTIONS]
```

**Options**:

* `--base <str>`: The baseline release.  [required]
* `--candidate <str>`: The candidate release.  [required]
* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--include-presentation`: Also print layout and display changes, which are never part of the narrative.
* `--cross-check`: Check the narrative against DataFusion and the Delta change feed (DATA-57).
* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture compare`

Compare a design alternative with the baseline it declares.

**Usage**:

```console
$ architecture compare [OPTIONS]
```

**Options**:

* `--baseline <str>`: A release on the baseline line.  [required]
* `--alternative <str>`: A release on a scenario line.  [required]
* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--baseline-store <path>`: Where the baseline lives. Defaults to --store.
* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture review`

Record a decision on a change report.

**Usage**:

```console
$ architecture review [OPTIONS] {change_report}
```

**Arguments**:

* `change_report`: A change report written by `change --format json`.  [required]

**Options**:

* `--decision <approved|changes_requested|rejected>`: The reviewer&#x27;s conclusion.  [required]
* `--reviewer <str>`: Who reviewed it.  [required]
* `--note <str>`: Why.
* `--into <path>`: Where to write the reviewed report.
* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--help`: Show this message and exit.

## `architecture output`

Reserved: distribute a release&#x27;s outputs (W8).

**Usage**:

```console
$ architecture output [OPTIONS]
```

**Options**:

* `--store <path>`: Release store root.  [default: .runtime/releases]
* `--release <str>`: Defaults to the current release.
* `--format <human|json>`: How to render the answer.  [default: human]
* `--help`: Show this message and exit.

## `architecture build`

Reserved: the full projection pipeline is not implemented.

**Usage**:

```console
$ architecture build [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.
