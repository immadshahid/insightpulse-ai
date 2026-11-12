import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_client.dart';
import '../core/brand.dart';
import '../core/share.dart';
import '../core/theme.dart';
import '../state/providers.dart';
import '../widgets/common.dart';
import '../widgets/motion.dart';
import '../widgets/visuals.dart';

/// Pick a month, build the PDF on the server, then share or save it.
class ReportScreen extends ConsumerStatefulWidget {
  const ReportScreen({super.key, required this.datasetId, required this.datasetName});

  final String datasetId;
  final String datasetName;

  @override
  ConsumerState<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends ConsumerState<ReportScreen> {
  String? _month;
  bool _busy = false;
  String? _error;
  ({Uint8List bytes, String name, String label})? _ready;

  static const _inside = [
    (Icons.dashboard_customize_outlined, 'Headline numbers', 'Compared with last month and last year'),
    (Icons.show_chart_rounded, 'Charts', 'Daily revenue, 12-month trend, top products and locations'),
    (Icons.groups_outlined, 'Customers', 'New and returning customers this month'),
    (Icons.fact_check_outlined, 'Data overview (EDA)', 'Data quality, columns and order statistics'),
    (Icons.lightbulb_outline, 'Findings and next steps', 'Key insights and recommended actions'),
    (Icons.auto_graph_rounded, 'Looking ahead', 'Your revenue forecast with its likely range'),
  ];

  String _fileName(String month) {
    final safe = widget.datasetName.replaceAll(RegExp(r'[^A-Za-z0-9]+'), '-').replaceAll(RegExp(r'^-|-$'), '');
    return 'InsightPulse-${safe.isEmpty ? 'report' : safe}-$month.pdf';
  }

  Future<void> _share() async {
    final ready = _ready;
    if (ready == null) return;
    await ref.read(fileSharerProvider)(ready.bytes, ready.name);
  }

  Future<void> _create(String month, String label) async {
    HapticFeedback.selectionClick();
    setState(() {
      _busy = true;
      _error = null;
      _ready = null;
    });
    try {
      final bytes = await ref.read(apiProvider).monthlyReport(widget.datasetId, month);
      if (!mounted) return;
      setState(() => _ready = (bytes: bytes, name: _fileName(month), label: label));
      await _share();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final months = ref.watch(reportMonthsProvider(widget.datasetId));
    return Scaffold(
      appBar: AppBar(title: const Text('Monthly report')),
      body: SafeArea(
        child: months.when(
          loading: () => ListView(padding: const EdgeInsets.all(16), children: const [
            Skeleton(height: 170, radius: kRadius + 4),
            SizedBox(height: 16),
            SkeletonCard(chart: false),
          ]),
          error: (e, _) => ErrorState(error: e, onRetry: () => ref.invalidate(reportMonthsProvider(widget.datasetId))),
          data: (m) {
            final selected = _month ?? m.defaultMonth;
            final label = m.months.where((x) => x.month == selected).firstOrNull?.label ?? selected;
            return ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
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
                      child: const Icon(Icons.picture_as_pdf_outlined, color: Colors.white, size: 30),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('Your month in one PDF',
                            style: t.titleLarge?.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
                        const SizedBox(height: 4),
                        Text('Charts, a data overview and your forecast, ready for a partner, investor or bank.',
                            style: t.bodyMedium?.copyWith(color: Colors.white.withValues(alpha: 0.88), height: 1.35)),
                      ]),
                    ),
                  ]),
                ),
              ),
              const SizedBox(height: 18),
              const SectionTitle('Choose a month'),
              SizedBox(
                height: 44,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: m.months.length,
                  separatorBuilder: (_, _) => const SizedBox(width: 8),
                  itemBuilder: (context, i) {
                    final item = m.months[i];
                    return ChoiceChip(
                      label: Text(item.label),
                      selected: item.month == selected,
                      showCheckmark: false,
                      onSelected: _busy ? null : (_) => setState(() => _month = item.month),
                    );
                  },
                ),
              ),
              const SizedBox(height: 18),
              const SectionTitle("What's inside"),
              AppCard(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                child: Column(children: [
                  for (final (i, (icon, title, detail)) in _inside.indexed) ...[
                    if (i > 0) const Divider(height: 1),
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      child: Row(children: [
                        IconBadge(icon: icon, color: Brand.indigo, size: 34),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(title, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                            Text(detail, style: t.bodySmall?.copyWith(color: p.muted)),
                          ]),
                        ),
                      ]),
                    ),
                  ],
                ]),
              ),
              const SizedBox(height: 18),
              if (_error != null) ...[InlineError(_error!), const SizedBox(height: 12)],
              if (_ready != null) ...[
                FadeSlideIn(
                  child: AppCard(
                    child: Row(children: [
                      IconBadge(icon: Icons.check_circle_outline, color: p.positive),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text('${_ready!.label} report is ready',
                              style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                          Text('${_ready!.name} · ${(_ready!.bytes.length / 1024).round()} KB',
                              style: t.bodySmall?.copyWith(color: p.muted)),
                        ]),
                      ),
                      TextButton.icon(
                        onPressed: _share,
                        icon: const Icon(Icons.ios_share_rounded, size: 18),
                        label: const Text('Share or save'),
                      ),
                    ]),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              SizedBox(
                height: 54,
                child: FilledButton.icon(
                  onPressed: _busy ? null : () => _create(selected, label),
                  icon: _busy
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.4))
                      : const Icon(Icons.picture_as_pdf_rounded),
                  label: Text(_busy ? 'Building your report...' : 'Create $label report'),
                ),
              ),
              const SizedBox(height: 8),
              Text('Usually takes 5 to 10 seconds.',
                  textAlign: TextAlign.center, style: t.labelMedium?.copyWith(color: p.muted)),
            ]);
          },
        ),
      ),
    );
  }
}
