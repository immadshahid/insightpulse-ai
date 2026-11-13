part of 'home_screen.dart';

/// Home for general data (Titanic, a survey, HR records...): a full EDA, findings,
/// charts, every column, and Predict for the outcome column.
class _ExploreHome extends ConsumerWidget {
  const _ExploreHome({required this.dataset, required this.name});

  final DatasetSummary dataset;
  final String name;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final picked = ref.watch(exploreTargetProvider)[dataset.id];
    final key = (datasetId: dataset.id, target: picked);
    final ex = ref.watch(exploreProvider(key));
    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(exploreProvider(key)),
      child: ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          _ExploreHero(
            name: name,
            summary: ex.when(
              skipLoadingOnReload: true,
              loading: () => const _GlassSkeleton(),
              error: (_, _) => const SizedBox.shrink(),
              data: (e) => FadeSlideIn(child: _OverviewCard(exploration: e)),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: ex.when(
                skipLoadingOnReload: true,
                loading: () => const [_DashboardSkeleton()],
                error: (e, _) => [
                  SizedBox(
                    height: 360,
                    child: ErrorState(error: e, onRetry: () => ref.invalidate(exploreProvider(key))),
                  ),
                ],
                data: (e) => _content(context, ref, e),
              ),
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _content(BuildContext context, WidgetRef ref, Exploration e) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    return [
      FadeSlideIn(child: _ExploreActions(dataset: dataset)),
      const SizedBox(height: 20),
      if (e.predictable.isNotEmpty) ...[
        FadeSlideIn(
          index: 1,
          child: _TargetPicker(
            exploration: e,
            onPicked: (target) {
              HapticFeedback.selectionClick();
              ref.read(exploreTargetProvider.notifier).set(dataset.id, target);
            },
          ),
        ),
        const SizedBox(height: 12),
      ],
      if (e.target != null)
        FadeSlideIn(
          index: 2,
          child: _PredictCard(key: ValueKey('${dataset.id}/${e.target}'), datasetId: dataset.id, target: e.target!),
        ),
      const SizedBox(height: 12),
      FadeSlideIn(index: 3, child: _ReportBanner(dataset: dataset)),
      if (e.insights.isNotEmpty) ...[
        const SizedBox(height: 16),
        SectionTitle(
          'What stands out',
          trailing: TextButton(onPressed: () => context.go('/insights'), child: const Text('See all')),
        ),
        for (final (i, insight) in e.insights.take(4).indexed) ...[
          if (i > 0) const SizedBox(height: 12),
          FadeSlideIn(index: 3 + i, child: InsightCard(insight: insight)),
        ],
      ],
      if (e.charts.isNotEmpty) ...[
        const SizedBox(height: 16),
        const SectionTitle('Charts'),
        for (final (i, c) in e.charts.indexed) ...[
          if (i > 0) const SizedBox(height: 12),
          AppCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(c.title, style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              Text(c.caption, style: t.bodySmall?.copyWith(color: p.muted)),
              const SizedBox(height: 12),
              ChartImage(c.url, title: c.title, semanticLabel: '${c.title}. ${c.caption}'),
            ]),
          ),
        ],
      ],
      const SizedBox(height: 16),
      SectionTitle('Every column', trailing: Text('${e.columns.length}', style: t.labelLarge?.copyWith(color: p.muted))),
      AppCard(
        padding: EdgeInsets.zero,
        child: Column(children: [
          for (final (i, c) in e.columns.indexed) ...[
            if (i > 0) const Divider(height: 1),
            _ColumnTile(column: c, isTarget: c.name == e.target),
          ],
        ]),
      ),
    ];
  }
}

class _ExploreHero extends StatelessWidget {
  const _ExploreHero({required this.name, required this.summary});

  final String name;
  final Widget summary;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final top = MediaQuery.paddingOf(context).top;
    final soft = Colors.white.withValues(alpha: 0.82);
    return Container(
      decoration: BoxDecoration(
        gradient: Brand.hero(Theme.of(context).brightness),
        borderRadius: const BorderRadius.vertical(bottom: Radius.circular(32)),
      ),
      child: Stack(children: [
        Positioned(right: -60, top: -40, child: _Glow(size: 200)),
        Positioned(left: -50, bottom: 60, child: _Glow(size: 140)),
        Padding(
          padding: EdgeInsets.fromLTRB(16, top + 10, 16, 18),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              _Avatar(name: name),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(greeting(DateTime.now()), style: t.bodyMedium?.copyWith(color: soft)),
                  Text(
                    name,
                    overflow: TextOverflow.ellipsis,
                    style: t.headlineSmall?.copyWith(color: Colors.white, fontWeight: FontWeight.w800),
                  ),
                ]),
              ),
              const _AccountMenu(color: Colors.white),
            ]),
            const SizedBox(height: 14),
            const Align(alignment: Alignment.centerLeft, child: DatasetChip()),
            const SizedBox(height: 16),
            summary,
          ]),
        ),
      ]),
    );
  }
}

/// Frosted card: rows, columns, completeness and the quality ring.
class _OverviewCard extends StatelessWidget {
  const _OverviewCard({required this.exploration});

  final Exploration exploration;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final e = exploration;
    final soft = Colors.white.withValues(alpha: 0.82);
    Widget stat(String value, String label) => Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text(value, style: t.headlineSmall?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
            ),
            Text(label, style: t.labelMedium?.copyWith(color: soft)),
          ]),
        );
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 14, 14, 16),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(kRadius + 4),
        border: Border.all(color: Colors.white.withValues(alpha: 0.24)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.18), borderRadius: BorderRadius.circular(20)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.travel_explore_rounded, color: Colors.white, size: 15),
            const SizedBox(width: 6),
            Text('Data exploration', style: t.labelMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
          ]),
        ),
        const SizedBox(height: 14),
        Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          stat((e.rows >= 10000 ? compactNumber(e.rows) : wholeNumber(e.rows)), 'rows'),
          stat('${e.columnCount}', 'columns'),
          stat('${e.completePct.round()}%', 'complete rows'),
          if (e.qualityScore != null)
            RingGauge(
              value: e.qualityScore!.toDouble(),
              color: Colors.white,
              size: 64,
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Text('${e.qualityScore}', style: t.titleMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
                Text('quality', style: t.labelSmall?.copyWith(color: soft, fontSize: 9)),
              ]),
            ),
        ]),
        if (e.insights.isNotEmpty) ...[
          const SizedBox(height: 14),
          Text(e.insights.first.headline,
              style: t.bodyLarge?.copyWith(color: Colors.white, height: 1.4, fontWeight: FontWeight.w500)),
        ],
      ]),
    );
  }
}

class _ExploreActions extends StatelessWidget {
  const _ExploreActions({required this.dataset});

  final DatasetSummary dataset;

  @override
  Widget build(BuildContext context) {
    void push(Widget screen) {
      HapticFeedback.selectionClick();
      Navigator.of(context, rootNavigator: true).push(MaterialPageRoute<void>(builder: (_) => screen));
    }

    final actions = [
      (Icons.auto_awesome, 'Ask AI', const [Color(0xFF6366F1), Color(0xFF8B5CF6)], () => context.go('/ask')),
      (Icons.lightbulb_rounded, 'Findings', const [Color(0xFF0EA5E9), Color(0xFF06B6D4)], () => context.go('/insights')),
      (Icons.folder_rounded, 'Data', const [Color(0xFFEC4899), Color(0xFFF43F5E)], () => context.go('/data')),
      (
        Icons.picture_as_pdf_rounded,
        'Report',
        const [Color(0xFFF59E0B), Color(0xFFF97316)],
        () => push(ReportScreen(datasetId: dataset.id, datasetName: dataset.name, general: true)),
      ),
    ];
    return _ActionRow(actions: actions);
  }
}

/// "Outcome to explain": which column the findings and Predict focus on.
class _TargetPicker extends StatelessWidget {
  const _TargetPicker({required this.exploration, required this.onPicked});

  final Exploration exploration;
  final ValueChanged<String> onPicked;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final e = exploration;
    return AppCard(
      child: Row(children: [
        IconBadge(icon: Icons.track_changes_rounded, color: Brand.indigo),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Outcome to explain', style: t.labelMedium?.copyWith(color: p.muted)),
            DropdownButtonHideUnderline(
              child: DropdownButton<String>(
                isExpanded: true,
                value: e.target != null && e.predictable.contains(e.target) ? e.target : null,
                hint: const Text('Pick a column'),
                style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                items: [
                  for (final c in e.predictable) DropdownMenuItem(value: c, child: Text(c, overflow: TextOverflow.ellipsis)),
                ],
                onChanged: (v) {
                  if (v != null) onPicked(v);
                },
              ),
            ),
          ]),
        ),
      ]),
    );
  }
}

/// Train a model for the outcome column on demand and show what drives it.
class _PredictCard extends ConsumerStatefulWidget {
  const _PredictCard({super.key, required this.datasetId, required this.target});

  final String datasetId;
  final String target;

  @override
  ConsumerState<_PredictCard> createState() => _PredictCardState();
}

class _PredictCardState extends ConsumerState<_PredictCard> {
  bool _started = false;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final header = Row(children: [
      Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(gradient: Brand.hero(Theme.of(context).brightness), borderRadius: BorderRadius.circular(14)),
        child: const Icon(Icons.psychology_alt_rounded, color: Colors.white, size: 24),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Predict ${widget.target}', style: t.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
          Text('Machine learning finds what drives it', style: t.bodySmall?.copyWith(color: p.muted)),
        ]),
      ),
    ]);
    if (!_started) {
      return AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          header,
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: () {
              HapticFeedback.selectionClick();
              setState(() => _started = true);
            },
            icon: const Icon(Icons.play_arrow_rounded),
            label: const Text('Train a model'),
          ),
        ]),
      );
    }
    final key = (datasetId: widget.datasetId, target: widget.target);
    final result = ref.watch(predictProvider(key));
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        header,
        const SizedBox(height: 14),
        ...result.when(
          loading: () => [
            Row(children: [
              const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.4)),
              const SizedBox(width: 12),
              Expanded(child: Text('Training and testing a model...', style: t.bodyMedium?.copyWith(color: p.muted))),
            ]),
          ],
          error: (e, _) => [InlineError('$e', onRetry: () => ref.invalidate(predictProvider(key)))],
          data: (r) => _result(context, r),
        ),
      ]),
    );
  }

  List<Widget> _result(BuildContext context, Prediction r) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final scoreText = '${(r.score.clamp(0, 1) * 100).round()}%';
    final scoreLabel = r.isClassification ? 'correct' : 'explained';
    final baseText = r.isClassification ? '${(r.baseline * 100).round()}%' : '0%';
    final maxImportance = r.features.isEmpty ? 1.0 : r.features.first.importance;
    return [
      Row(children: [
        _ScoreBlock(value: scoreText, label: 'Model: $scoreLabel', color: p.positive),
        const SizedBox(width: 10),
        _ScoreBlock(value: baseText, label: r.isClassification ? 'Guessing' : 'Baseline', color: p.muted),
      ]),
      const SizedBox(height: 12),
      Text(r.verdict, style: t.bodyMedium?.copyWith(height: 1.4)),
      if (r.features.isNotEmpty) ...[
        const SizedBox(height: 14),
        Text('What matters most', style: t.labelLarge?.copyWith(color: p.muted, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        for (final f in r.features.take(6))
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(children: [
              SizedBox(width: 110, child: Text(f.column, overflow: TextOverflow.ellipsis, style: t.bodyMedium)),
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: LinearProgressIndicator(
                    value: maxImportance <= 0 ? 0 : f.importance / maxImportance,
                    minHeight: 10,
                    backgroundColor: p.border,
                    color: Brand.indigo,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              SizedBox(
                width: 40,
                child: Text('${(f.importance * 100).round()}%',
                    textAlign: TextAlign.end, style: t.labelLarge?.copyWith(fontWeight: FontWeight.w700)),
              ),
            ]),
          ),
      ],
      const SizedBox(height: 10),
      Text(
        'Tested with 5-fold cross-validation on ${wholeNumber(r.rowsUsed)} rows.'
        '${r.excluded.isEmpty ? '' : ' Left out ${r.excluded.join(', ')} because it repeats ${r.target}.'}',
        style: t.bodySmall?.copyWith(color: p.muted),
      ),
    ];
  }
}

class _ScoreBlock extends StatelessWidget {
  const _ScoreBlock({required this.value, required this.label, required this.color});

  final String value;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(value, style: t.headlineSmall?.copyWith(color: color, fontWeight: FontWeight.w800)),
          Text(label, style: t.labelMedium?.copyWith(color: context.palette.muted)),
        ]),
      ),
    );
  }
}

/// One column: name, type, missing share; tap to see its statistics or common values.
class _ColumnTile extends StatelessWidget {
  const _ColumnTile({required this.column, required this.isTarget});

  final ExploreColumn column;
  final bool isTarget;

  static const _kindLabels = {
    'numeric': ('Number', Icons.numbers_rounded),
    'category': ('Category', Icons.category_outlined),
    'yes/no': ('Two values', Icons.toggle_on_outlined),
    'date': ('Date', Icons.event_outlined),
    'text': ('Text', Icons.notes_rounded),
    'id': ('ID', Icons.tag_rounded),
  };

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final c = column;
    final (kindLabel, icon) = _kindLabels[c.kind] ?? (c.kind, Icons.help_outline);
    final missing = c.missingPct >= 0.05 ? ' · ${c.missingPct.toStringAsFixed(c.missingPct < 10 ? 1 : 0)}% missing' : '';
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: const EdgeInsets.symmetric(horizontal: 16),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
        leading: IconBadge(icon: icon, color: isTarget ? Brand.violet : Brand.indigo, size: 34),
        title: Row(children: [
          Flexible(child: Text(c.name, overflow: TextOverflow.ellipsis, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700))),
          if (isTarget) ...[const SizedBox(width: 6), const Pill('Outcome')],
        ]),
        subtitle: Text('$kindLabel · ${wholeNumber(c.unique)} distinct$missing',
            style: t.bodySmall?.copyWith(color: c.missingPct >= 20 ? p.negative : p.muted)),
        children: [
          if (c.stats.isNotEmpty)
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final s in c.stats)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(color: p.accentSoft, borderRadius: BorderRadius.circular(10)),
                  child: Text.rich(TextSpan(children: [
                    TextSpan(text: '${s.label} ', style: t.labelMedium?.copyWith(color: p.muted)),
                    TextSpan(text: s.value, style: t.labelLarge?.copyWith(fontWeight: FontWeight.w700)),
                  ])),
                ),
            ]),
          if (c.topValues.isNotEmpty) ...[
            if (c.stats.isNotEmpty) const SizedBox(height: 10),
            for (final v in c.topValues.take(6))
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(children: [
                  SizedBox(width: 110, child: Text(v.value, overflow: TextOverflow.ellipsis, style: t.bodyMedium)),
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(6),
                      child: LinearProgressIndicator(
                        value: v.share / 100,
                        minHeight: 8,
                        backgroundColor: p.border,
                        color: Brand.violet,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  SizedBox(
                    width: 44,
                    child: Text('${v.share.toStringAsFixed(v.share < 10 ? 1 : 0)}%',
                        textAlign: TextAlign.end, style: t.labelMedium?.copyWith(color: p.muted)),
                  ),
                ]),
              ),
          ],
        ],
      ),
    );
  }
}
