import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/theme.dart';
import '../data/models.dart';
import '../state/providers.dart';
import 'common.dart';

/// Shows loading / no-data / needs-mapping states, else builds with the ready dataset.
class DatasetGate extends ConsumerWidget {
  const DatasetGate({super.key, required this.builder});

  final Widget Function(BuildContext context, DatasetSummary dataset) builder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(datasetsProvider);
    final current = ref.watch(currentDatasetProvider);
    if (list.isLoading && !list.hasValue) {
      return ListView(padding: const EdgeInsets.all(16), children: const [
        SkeletonCard(chart: false),
        SizedBox(height: 12),
        SkeletonCard(),
      ]);
    }
    if (list.hasError && !list.hasValue) {
      return ErrorState(error: list.error!, onRetry: () => ref.invalidate(datasetsProvider));
    }
    if (current == null) {
      return EmptyState(
        icon: Icons.upload_file_rounded,
        title: 'Add your sales data',
        message: 'Upload a CSV or Excel export of your orders. We will build your dashboard automatically.',
        action: 'Upload data',
        onAction: () => context.go('/data'),
      );
    }
    if (!current.isReady) {
      return EmptyState(
        icon: Icons.rule_rounded,
        title: 'Confirm your columns',
        message: "We couldn't tell which columns hold the date and revenue in "
            '"${current.name}". Pick them on the Data tab.',
        action: 'Open Data',
        onAction: () => context.go('/data'),
      );
    }
    return builder(context, current);
  }
}

/// Tappable chip with the current dataset's name; opens a switcher sheet.
class DatasetChip extends ConsumerWidget {
  const DatasetChip({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final current = ref.watch(currentDatasetProvider);
    if (current == null) return const SizedBox.shrink();
    final p = context.palette;
    return Semantics(
      button: true,
      label: 'Dataset ${current.name}. Change dataset',
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: () => _showPicker(context, ref),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: kMinTouch),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: p.card,
              border: Border.all(color: p.border),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.table_chart_outlined, size: 18, color: p.accent),
              const SizedBox(width: 6),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 170),
                child: Text(current.name, overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w600)),
              ),
              Icon(Icons.expand_more_rounded, size: 20, color: p.muted),
            ]),
          ),
        ),
      ),
    );
  }

  void _showPicker(BuildContext context, WidgetRef ref) {
    final list = ref.read(datasetsProvider).value ?? const [];
    final current = ref.read(currentDatasetProvider);
    showModalBottomSheet<void>(
      useRootNavigator: true,
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: ListView(shrinkWrap: true, children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(20, 0, 20, 8),
            child: Text('Your datasets', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          ),
          for (final d in list)
            ListTile(
              minTileHeight: kMinTouch,
              leading: Icon(d.id == current?.id ? Icons.radio_button_checked : Icons.radio_button_off,
                  color: sheet.palette.accent),
              title: Text(d.name),
              subtitle: Text(d.isReady
                  ? '${d.rowCount} rows${d.dateMin != null ? ' · ${d.dateMin} to ${d.dateMax}' : ''}'
                  : 'Needs column mapping'),
              onTap: () {
                ref.read(selectedDatasetIdProvider.notifier).select(d.id);
                Navigator.pop(sheet);
              },
            ),
          ListTile(
            minTileHeight: kMinTouch,
            leading: const Icon(Icons.add_rounded),
            title: const Text('Upload new data'),
            onTap: () {
              Navigator.pop(sheet);
              context.go('/data');
            },
          ),
        ]),
      ),
    );
  }
}
