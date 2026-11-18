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

/// Clean a dataset by typing what to fix, or by tapping fixes the app suggests.
/// Every change is previewed, and applying creates a new dataset; the original is kept.
class CleanScreen extends ConsumerStatefulWidget {
  const CleanScreen({super.key, required this.dataset});

  final DatasetSummary dataset;

  @override
  ConsumerState<CleanScreen> createState() => _CleanScreenState();
}

class _CleanScreenState extends ConsumerState<CleanScreen> {
  static const _examples = [
    'Remove rows where age is missing',
    "Change 'lhr' to 'Lahore' in City",
    'Keep only rows where amount is above 100',
  ];

  final _input = TextEditingController();
  final _focus = FocusNode();

  CleanSuggestions? _suggestions;
  String? _suggestionsError;

  /// The plan so far, and the server's description of what it does.
  List<CleanStep> _steps = [];
  CleanPreview? _preview;

  bool _planning = false;
  bool _checking = false;
  bool _applying = false;
  String? _error;

  /// What the AI left out of the last typed request, if anything.
  String? _note;

  String get _id => widget.dataset.id;
  bool get _busy => _planning || _checking || _applying;

  @override
  void initState() {
    super.initState();
    _loadSuggestions();
  }

  @override
  void dispose() {
    _input.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _loadSuggestions() async {
    setState(() => _suggestionsError = null);
    try {
      final s = await ref.read(apiProvider).cleanSuggestions(_id);
      if (mounted) setState(() => _suggestions = s);
    } on ApiException catch (e) {
      if (mounted) setState(() => _suggestionsError = e.message);
    }
  }

  /// Checks [steps] with the server; keeps the previous plan if they don't fit.
  Future<bool> _setSteps(List<CleanStep> steps) async {
    if (steps.isEmpty) {
      setState(() {
        _steps = [];
        _preview = null;
        _error = null;
      });
      return true;
    }
    setState(() {
      _checking = true;
      _error = null;
    });
    try {
      final preview = await ref.read(apiProvider).cleanPreview(_id, steps);
      if (!mounted) return false;
      setState(() {
        // Use the server's copy of each step: column names are corrected there.
        _steps = [for (final s in preview.steps) s.step];
        _preview = preview;
      });
      return true;
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
      return false;
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _ask() async {
    final text = _input.text.trim();
    if (text.length < 2 || _busy) return;
    HapticFeedback.selectionClick();
    _focus.unfocus();
    setState(() {
      _planning = true;
      _error = null;
      _note = null;
    });
    try {
      final plan = await ref.read(apiProvider).cleanPlan(_id, text);
      if (!mounted) return;
      setState(() => _planning = false);
      if (await _setSteps([..._steps, ...plan.steps])) {
        _input.clear();
        if (mounted) setState(() => _note = plan.note);
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _planning = false);
    }
  }

  Future<void> _apply() async {
    if (_steps.isEmpty || _busy) return;
    HapticFeedback.selectionClick();
    setState(() {
      _applying = true;
      _error = null;
    });
    try {
      final profile = await ref.read(apiProvider).cleanApply(_id, _steps);
      ref.invalidate(datasetsProvider);
      ref.read(selectedDatasetIdProvider.notifier).select(profile.dataset.id);
      if (!mounted) return;
      Navigator.of(context).pop();
      context.go('/home');
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _applying = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final suggestions = _suggestions;
    final preview = _preview;
    final aiOn = suggestions?.aiAvailable ?? true;
    // Suggestions already in the plan are hidden.
    final open = [
      for (final s in suggestions?.items ?? const <({String label, List<CleanStep> steps})>[])
        if (!_added.contains(s.label)) s,
    ];
    return Scaffold(
      appBar: AppBar(title: const Text('Clean data')),
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
                  child: const Icon(Icons.cleaning_services_rounded, color: Colors.white, size: 30),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Tell me what to fix',
                        style: t.titleLarge?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 4),
                    Text(
                      'Describe the change in your own words. You see exactly what it does first, '
                      'and "${widget.dataset.name}" itself is never changed.',
                      style: t.bodyMedium?.copyWith(color: Colors.white.withValues(alpha: 0.88), height: 1.35),
                    ),
                  ]),
                ),
              ]),
            ),
          ),
          const SizedBox(height: 16),
          if (aiOn) ...[
            TextField(
              controller: _input,
              focusNode: _focus,
              enabled: !_busy,
              minLines: 1,
              maxLines: 3,
              maxLength: 500,
              textInputAction: TextInputAction.send,
              textCapitalization: TextCapitalization.sentences,
              onSubmitted: (_) => _ask(),
              decoration: InputDecoration(
                hintText: 'e.g. ${_examples.first}',
                counterText: '',
                suffixIcon: _planning
                    ? const Padding(
                        padding: EdgeInsets.all(14),
                        child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.4)),
                      )
                    : IconButton(
                        tooltip: 'Add this change',
                        icon: const Icon(Icons.send_rounded),
                        onPressed: _busy ? null : _ask,
                      ),
              ),
            ),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 4, children: [
              for (final e in _examples)
                ActionChip(
                  label: Text(e, style: t.labelMedium),
                  onPressed: _busy
                      ? null
                      : () {
                          _input.text = e;
                          _focus.requestFocus();
                        },
                ),
            ]),
          ] else
            AppCard(
              child: Row(children: [
                Icon(Icons.info_outline_rounded, color: p.muted),
                const SizedBox(width: 12),
                Expanded(
                  child: Text('Typed requests need AI, which is off on this server. The suggested fixes below still work.',
                      style: t.bodyMedium?.copyWith(color: p.muted)),
                ),
              ]),
            ),
          if (_error != null) ...[const SizedBox(height: 12), InlineError(_error!)],
          if (_note != null) ...[
            const SizedBox(height: 12),
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(Icons.info_outline_rounded, size: 18, color: p.muted),
              const SizedBox(width: 8),
              Expanded(child: Text(_note!, style: t.bodySmall?.copyWith(color: p.muted, height: 1.35))),
            ]),
          ],
          const SizedBox(height: 18),
          if (suggestions == null && _suggestionsError == null)
            const SkeletonCard(chart: false)
          else if (_suggestionsError != null)
            AppCard(child: InlineError(_suggestionsError!, onRetry: _loadSuggestions))
          else if (open.isNotEmpty) ...[
            const SectionTitle('Suggested fixes'),
            AppCard(
              padding: EdgeInsets.zero,
              child: Column(children: [
                for (final (i, s) in open.indexed) ...[
                  if (i > 0) const Divider(height: 1),
                  ListTile(
                    minTileHeight: kMinTouch,
                    enabled: !_busy,
                    leading: IconBadge(icon: Icons.auto_fix_high_rounded, color: Brand.indigo, size: 34),
                    title: Text(s.label, style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
                    trailing: Icon(Icons.add_circle_outline_rounded, color: p.accent),
                    onTap: () async {
                      HapticFeedback.selectionClick();
                      if (await _setSteps([..._steps, ...s.steps])) _added.add(s.label);
                      if (mounted) setState(() {});
                    },
                  ),
                ],
              ]),
            ),
          ] else if (_steps.isEmpty)
            Text('No obvious problems found. Type a change above if you want one.',
                textAlign: TextAlign.center, style: t.bodyMedium?.copyWith(color: p.muted)),
          if (preview != null) ...[
            const SizedBox(height: 18),
            SectionTitle(
              'Changes to apply',
              trailing: TextButton(
                onPressed: _busy
                    ? null
                    : () {
                        _added.clear();
                        _setSteps([]);
                      },
                child: const Text('Clear all'),
              ),
            ),
            FadeSlideIn(
              child: AppCard(
                padding: EdgeInsets.zero,
                child: Column(children: [
                  for (final (i, s) in preview.steps.indexed) ...[
                    if (i > 0) const Divider(height: 1),
                    ListTile(
                      minTileHeight: kMinTouch,
                      leading: CircleAvatar(
                        radius: 14,
                        backgroundColor: p.accentSoft,
                        child: Text('${i + 1}', style: t.labelMedium?.copyWith(color: p.accent, fontWeight: FontWeight.w800)),
                      ),
                      title: Text(s.description, style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
                      subtitle: Text(s.effect, style: t.bodySmall?.copyWith(color: p.muted)),
                      trailing: IconButton(
                        tooltip: 'Remove this change',
                        icon: const Icon(Icons.close_rounded),
                        onPressed: _busy
                            ? null
                            : () {
                                _added.clear(); // suggestions may apply again
                                _setSteps([..._steps]..removeAt(i));
                              },
                      ),
                    ),
                  ],
                ]),
              ),
            ),
            const SizedBox(height: 12),
            _ResultSummary(preview: preview),
          ],
          const SizedBox(height: 18),
          SizedBox(
            height: 54,
            child: FilledButton.icon(
              onPressed: preview != null && !_busy ? _apply : null,
              icon: _applying || _checking
                  ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.4))
                  : const Icon(Icons.check_circle_outline_rounded),
              label: Text(_applying
                  ? 'Cleaning and analysing...'
                  : _checking
                      ? 'Checking...'
                      : 'Create cleaned copy'),
            ),
          ),
          const SizedBox(height: 8),
          Text('A new dataset is created. The original stays as it is.',
              textAlign: TextAlign.center, style: t.labelMedium?.copyWith(color: p.muted)),
        ]),
      ),
    );
  }

  /// Labels of suggestions already added to the plan.
  final Set<String> _added = {};
}

/// "43 rows → 40 rows · 6 columns → 5 columns".
class _ResultSummary extends StatelessWidget {
  const _ResultSummary({required this.preview});

  final CleanPreview preview;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final v = preview;
    Widget block(String label, int before, int after) => Expanded(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(color: p.accentSoft, borderRadius: BorderRadius.circular(14)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: t.labelMedium?.copyWith(color: p.muted)),
              const SizedBox(height: 2),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(
                  before == after ? wholeNumber(after) : '${wholeNumber(before)} → ${wholeNumber(after)}',
                  style: t.titleMedium?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
            ]),
          ),
        );
    return Row(children: [
      block('Rows', v.rowsBefore, v.rowsAfter),
      const SizedBox(width: 10),
      block('Columns', v.columnsBefore, v.columnsAfter),
    ]);
  }
}
