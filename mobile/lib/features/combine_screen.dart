import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api_client.dart';
import '../core/brand.dart';
import '../core/format.dart';
import '../core/theme.dart';
import '../data/models.dart';
import '../state/providers.dart';
import '../widgets/common.dart';
import '../widgets/motion.dart';
import '../widgets/visuals.dart';

/// Multi-file analysis: pick two or more datasets, see how they fit together, and
/// create a new combined dataset. The originals are kept.
class CombineScreen extends ConsumerStatefulWidget {
  const CombineScreen({super.key});

  @override
  ConsumerState<CombineScreen> createState() => _CombineScreenState();
}

class _CombineScreenState extends ConsumerState<CombineScreen> {
  static const _maxFiles = 6;

  /// Chosen dataset ids, in the order they were ticked.
  final List<String> _chosen = [];
  final _name = TextEditingController();

  CombinePreview? _preview;
  bool _checking = false;
  String? _previewError;
  String? _mode;
  bool _creating = false;
  String? _createError;

  /// Guards against an older preview answer arriving after a newer selection.
  int _request = 0;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _toggle(String id) {
    HapticFeedback.selectionClick();
    setState(() {
      if (_chosen.contains(id)) {
        _chosen.remove(id);
      } else if (_chosen.length < _maxFiles) {
        _chosen.add(id);
      }
      _preview = null;
      _previewError = null;
      _createError = null;
      _mode = null;
    });
    if (_chosen.length >= 2) _loadPreview();
  }

  Future<void> _loadPreview() async {
    final request = ++_request;
    setState(() => _checking = true);
    try {
      final preview = await ref.read(apiProvider).combinePreview(List.of(_chosen));
      if (!mounted || request != _request) return;
      setState(() {
        _preview = preview;
        _mode = preview.suggested;
      });
    } on ApiException catch (e) {
      if (mounted && request == _request) setState(() => _previewError = e.message);
    } finally {
      if (mounted && request == _request) setState(() => _checking = false);
    }
  }

  Future<void> _create() async {
    final mode = _mode;
    if (mode == null) return;
    HapticFeedback.selectionClick();
    setState(() {
      _creating = true;
      _createError = null;
    });
    try {
      final name = _name.text.trim();
      final profile = await ref.read(apiProvider).combine(List.of(_chosen), mode, name: name.isEmpty ? null : name);
      ref.invalidate(datasetsProvider);
      ref.read(selectedDatasetIdProvider.notifier).select(profile.dataset.id);
      if (!mounted) return;
      Navigator.of(context).pop();
      context.go('/home');
    } on ApiException catch (e) {
      if (mounted) setState(() => _createError = e.message);
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final datasets = (ref.watch(datasetsProvider).value ?? const <DatasetSummary>[]);
    final preview = _preview;
    final canCreate = preview != null && _mode != null && !_creating;
    return Scaffold(
      appBar: AppBar(title: const Text('Combine datasets')),
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
          FadeSlideIn(
            child: GradientCard(
              child: Row(children: [
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.18),
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.3)),
                  ),
                  child: const Icon(Icons.join_inner_rounded, color: Colors.white, size: 30),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Analyse files together',
                        style: t.titleLarge?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 4),
                    Text(
                      'Stack monthly files into one, or link orders with customers and products. '
                      'Your original datasets are kept.',
                      style: t.bodyMedium?.copyWith(color: Colors.white.withValues(alpha: 0.88), height: 1.35),
                    ),
                  ]),
                ),
              ]),
            ),
          ),
          const SizedBox(height: 18),
          SectionTitle(
            'Choose 2 or more',
            trailing: Text('${_chosen.length} selected', style: t.labelLarge?.copyWith(color: p.muted)),
          ),
          AppCard(
            padding: EdgeInsets.zero,
            child: Column(children: [
              for (final (i, d) in datasets.indexed) ...[
                if (i > 0) const Divider(height: 1),
                CheckboxListTile(
                  value: _chosen.contains(d.id),
                  onChanged: _creating || (!_chosen.contains(d.id) && _chosen.length >= _maxFiles)
                      ? null
                      : (_) => _toggle(d.id),
                  controlAffinity: ListTileControlAffinity.leading,
                  title: Text(d.name, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600)),
                  subtitle: Text(
                    '${wholeNumber(d.rowCount)} rows · ${d.isGeneral ? 'General data' : 'Sales data'}',
                    style: t.bodySmall?.copyWith(color: p.muted),
                  ),
                ),
              ],
            ]),
          ),
          const SizedBox(height: 18),
          if (_chosen.length < 2)
            Text('Tick at least two datasets to see how they fit together.',
                textAlign: TextAlign.center, style: t.bodyMedium?.copyWith(color: p.muted))
          else if (_checking)
            const SkeletonCard(chart: false)
          else if (_previewError != null)
            AppCard(child: InlineError(_previewError!, onRetry: _loadPreview))
          else if (preview != null) ...[
            const SectionTitle('How to combine'),
            FadeSlideIn(child: _PlanCard(preview: preview, mode: _mode, onMode: (m) => setState(() => _mode = m))),
            if (_mode != null) ...[
              const SizedBox(height: 14),
              TextField(
                controller: _name,
                enabled: !_creating,
                maxLength: 60,
                textCapitalization: TextCapitalization.sentences,
                decoration: const InputDecoration(
                  labelText: 'Name (optional)',
                  hintText: 'e.g. Full year 2026',
                  counterText: '',
                ),
              ),
            ],
          ],
          if (_createError != null) ...[const SizedBox(height: 12), InlineError(_createError!)],
          const SizedBox(height: 18),
          SizedBox(
            height: 54,
            child: FilledButton.icon(
              onPressed: canCreate ? _create : null,
              icon: _creating
                  ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.4))
                  : const Icon(Icons.auto_awesome_motion_rounded),
              label: Text(_creating
                  ? 'Combining and analysing...'
                  : _chosen.length < 2
                      ? 'Combine datasets'
                      : 'Combine ${_chosen.length} datasets'),
            ),
          ),
        ]),
      ),
    );
  }
}

/// Stack / Join choice with what each would produce (or why it can't be done).
class _PlanCard extends StatelessWidget {
  const _PlanCard({required this.preview, required this.mode, required this.onMode});

  final CombinePreview preview;
  final String? mode;
  final ValueChanged<String> onMode;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final v = preview;
    if (!v.stackPossible && !v.joinPossible) {
      return AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            IconBadge(icon: Icons.link_off_rounded, color: p.negative),
            const SizedBox(width: 12),
            Expanded(
              child: Text("These files don't fit together yet",
                  style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            ),
          ]),
          const SizedBox(height: 10),
          Text(v.joinReason ?? v.stackReason ?? 'Try a different selection.',
              style: t.bodyMedium?.copyWith(color: p.muted, height: 1.4)),
        ]),
      );
    }
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SegmentedButton<String>(
          segments: [
            ButtonSegment(
              value: 'stack',
              enabled: v.stackPossible,
              icon: const Icon(Icons.table_rows_rounded),
              label: const Text('Stack'),
            ),
            ButtonSegment(
              value: 'join',
              enabled: v.joinPossible,
              icon: const Icon(Icons.join_inner_rounded),
              label: const Text('Join'),
            ),
          ],
          selected: {?mode},
          emptySelectionAllowed: true,
          showSelectedIcon: false,
          onSelectionChanged: (s) {
            if (s.isNotEmpty) onMode(s.first);
          },
        ),
        const SizedBox(height: 14),
        if (mode == 'stack') ..._stack(context) else ..._join(context),
      ]),
    );
  }

  List<Widget> _stack(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final v = preview;
    return [
      Text('One table with every file under the next',
          style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
      const SizedBox(height: 6),
      Text(
        '${wholeNumber(v.stackRows)} rows and ${v.stackColumns} columns. '
        '${v.sharedColumns.length} columns are in every file. A "Source file" column records where '
        'each row came from, so you can compare the files.',
        style: t.bodyMedium?.copyWith(color: p.muted, height: 1.4),
      ),
      if (v.partialColumns.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text(
          'Only in some files (left empty elsewhere): ${v.partialColumns.take(6).join(', ')}'
          '${v.partialColumns.length > 6 ? ' and ${v.partialColumns.length - 6} more' : ''}.',
          style: t.bodySmall?.copyWith(color: p.muted),
        ),
      ],
    ];
  }

  List<Widget> _join(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final v = preview;
    return [
      Text('${v.joinBase ?? 'The main file'} with details added from the others',
          style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
      const SizedBox(height: 6),
      Text(
        '${wholeNumber(v.joinRows)} rows and ${v.joinColumns} columns. Every row of '
        '${v.joinBase ?? 'the main file'} is kept.',
        style: t.bodyMedium?.copyWith(color: p.muted, height: 1.4),
      ),
      const SizedBox(height: 10),
      for (final s in v.joinSteps)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            IconBadge(icon: Icons.link_rounded, color: Brand.indigo, size: 32),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${s.right} linked by ${s.leftColumn}',
                    style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
                Text(
                  '${s.matchPct.round()}% of rows matched · adds ${s.columnsAdded} '
                  'column${s.columnsAdded == 1 ? '' : 's'}'
                  '${s.leftColumn == s.rightColumn ? '' : ' · "${s.rightColumn}" in ${s.right}'}',
                  style: t.bodySmall?.copyWith(color: s.matchPct < 80 ? p.negative : p.muted),
                ),
              ]),
            ),
          ]),
        ),
    ];
  }
}
