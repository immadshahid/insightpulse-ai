import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
import '../data/models.dart';
import '../state/providers.dart';
import '../widgets/common.dart';
import '../widgets/dataset_gate.dart';
import '../widgets/visuals.dart';

const roleLabels = {
  'date': 'Date',
  'revenue': 'Revenue',
  'quantity': 'Quantity',
  'product': 'Product',
  'customer': 'Customer',
  'region': 'City / region',
  'order_id': 'Order ID',
};

const _roleHelp = {
  'date': 'When the sale happened',
  'revenue': 'Money received for the row',
  'quantity': 'Number of units',
  'product': 'Product or category',
  'customer': 'Customer ID (preferred) or name',
  'region': 'City, region or branch',
  'order_id': 'Order, invoice or receipt number',
};

class DataScreen extends ConsumerStatefulWidget {
  const DataScreen({super.key});

  @override
  ConsumerState<DataScreen> createState() => _DataScreenState();
}

class _DataScreenState extends ConsumerState<DataScreen> {
  bool _uploading = false;
  bool _saving = false;
  String? _uploadError;

  /// What the upload is doing now, and how much of the file has been sent (0..1).
  String? _stage;
  double? _progress;

  static const _maxUploadBytes = 25 * 1024 * 1024; // the server's limit

  /// role -> column while the user is editing (null = no unsaved edits).
  Map<String, String?>? _edited;
  String? _editedFor;

  Future<void> _pickAndUpload() async {
    final file = await FilePicker.pickFile(
      type: FileType.custom,
      allowedExtensions: const ['csv', 'xlsx', 'xls'],
    );
    if (file == null) return;
    setState(() => _stage = 'Opening your file...');
    await _load(() async {
      final bytes = await file.readAsBytes();
      if (bytes.length > _maxUploadBytes) {
        throw ApiException(
          'That file is ${(bytes.length / 1048576).toStringAsFixed(1)} MB; the limit is 25 MB. '
          'Export fewer months or remove columns you do not need.',
        );
      }
      if (mounted) {
        setState(() {
          _stage = 'Sending file';
          _progress = 0;
        });
      }
      return ref.read(apiProvider).upload(bytes, file.name, onProgress: _onProgress);
    });
  }

  void _onProgress(double fraction) {
    if (!mounted) return;
    final done = fraction >= 0.999;
    // Repaint only on whole-percent steps.
    if (!done && _progress != null && (fraction - _progress!).abs() < 0.01) return;
    setState(() {
      _progress = fraction.clamp(0, 1).toDouble();
      if (done) _stage = 'Reading your data...';
    });
  }

  Future<void> _importSheet() async {
    final link = await showDialog<String>(context: context, builder: (_) => const _SheetDialog());
    if (link == null || link.isEmpty || !mounted) return;
    await _load(() => ref.read(apiProvider).importSheet(link));
  }

  /// Runs one way of adding data, then makes the new dataset the current one.
  Future<void> _load(Future<DatasetProfile> Function() add) async {
    setState(() {
      _uploading = true;
      _uploadError = null;
    });
    try {
      final profile = await add();
      ref.invalidate(datasetsProvider);
      ref.read(selectedDatasetIdProvider.notifier).select(profile.dataset.id);
      setState(() => _edited = null);
    } on ApiException catch (e) {
      if (mounted) setState(() => _uploadError = e.message);
    } finally {
      if (mounted) {
        setState(() {
          _uploading = false;
          _stage = null;
          _progress = null;
        });
      }
    }
  }

  Future<void> _delete(DatasetSummary dataset) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Delete this dataset?'),
        content: Text('"${dataset.name}" and its dashboards and forecasts will be removed for good.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialog, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(dialog, true), child: const Text('Delete')),
        ],
      ),
    );
    if (sure != true || !mounted) return;
    try {
      await ref.read(apiProvider).deleteDataset(dataset.id);
      ref.read(selectedDatasetIdProvider.notifier).select(null);
      ref.invalidate(datasetsProvider);
      setState(() => _edited = null);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  /// General data the user says is sales data: show the column roles to confirm.
  bool _salesSetup = false;
  String? _salesSetupFor;

  Future<void> _switchKind(DatasetProfile profile, String kind) async {
    HapticFeedback.selectionClick();
    setState(() => _saving = true);
    try {
      await ref.read(apiProvider).setKind(profile.dataset.id, kind);
      ref.invalidate(profileProvider(profile.dataset.id));
      ref.invalidate(datasetsProvider);
      setState(() {
        _edited = null;
        _salesSetup = false;
      });
      if (mounted) context.go('/home');
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _buildDashboard(DatasetProfile profile) async {
    final edits = _edited;
    if (edits == null && profile.dataset.isGeneral && _salesSetup) {
      // The suggested roles are already complete: just analyse it as sales data.
      return _switchKind(profile, 'sales');
    }
    if (edits != null) {
      setState(() => _saving = true);
      try {
        await ref.read(apiProvider).saveMapping(profile.dataset.id, edits);
        ref.invalidate(profileProvider(profile.dataset.id));
        ref.invalidate(datasetsProvider);
        setState(() => _edited = null);
      } on ApiException catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
        }
        return;
      } finally {
        if (mounted) setState(() => _saving = false);
      }
    }
    if (mounted) context.go('/home');
  }

  void _assign(DatasetProfile profile, String column, String? role) {
    final mapping = Map<String, String?>.from(_edited ?? profile.mapping);
    mapping.updateAll((r, c) => c == column ? null : c); // column leaves its old role
    if (role != null) mapping[role] = column; // role moves to this column
    setState(() {
      _edited = mapping;
      _editedFor = profile.dataset.id;
    });
  }

  @override
  Widget build(BuildContext context) {
    final current = ref.watch(currentDatasetProvider);
    if (_editedFor != null && _editedFor != current?.id) _edited = null;
    if (_salesSetupFor != current?.id) _salesSetup = false;
    return Scaffold(
      appBar: AppBar(title: const Text('Data'), actions: [
        const DatasetChip(),
        // Also here, so a new account with no data yet can still sign out.
        IconButton(
          tooltip: 'Sign out',
          icon: const Icon(Icons.logout_rounded),
          onPressed: () => ref.read(authProvider.notifier).logout(),
        ),
        const SizedBox(width: 4),
      ]),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(datasetsProvider);
          if (current != null) ref.invalidate(profileProvider(current.id));
        },
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
          children: [
            _UploadCard(
              busy: _uploading,
              stage: _stage,
              progress: _progress,
              error: _uploadError,
              onPick: _pickAndUpload,
              onSample: () => _load(() => ref.read(apiProvider).loadSample()),
            ),
            const SizedBox(height: 12),
            _SheetCard(busy: _uploading, onTap: _importSheet),
            if (current != null) ...[
              const SizedBox(height: 20),
              ref.watch(profileProvider(current.id)).when(
                    loading: () => const SkeletonCard(chart: false),
                    error: (e, _) => AppCard(
                      child: InlineError('$e', onRetry: () => ref.invalidate(profileProvider(current.id))),
                    ),
                    data: (profile) => _ProfileSection(
                      profile: profile,
                      mapping: _edited ?? profile.mapping,
                      dirty: _edited != null,
                      saving: _saving,
                      onAssign: (column, role) => _assign(profile, column, role),
                      onBuild: () => _buildDashboard(profile),
                      onDelete: () => _delete(profile.dataset),
                      salesSetup: _salesSetup,
                      onGeneral: () => _switchKind(profile, 'general'),
                      onSales: () => setState(() {
                        _salesSetup = true;
                        _salesSetupFor = profile.dataset.id;
                      }),
                    ),
                  ),
            ],
          ],
        ),
      ),
    );
  }
}

class _UploadCard extends StatelessWidget {
  const _UploadCard({
    required this.busy,
    required this.error,
    required this.onPick,
    required this.onSample,
    this.stage,
    this.progress,
  });

  final bool busy;
  final String? stage;
  final double? progress;
  final String? error;
  final VoidCallback onPick;
  final VoidCallback onSample;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: p.accentSoft, borderRadius: BorderRadius.circular(14)),
            child: Icon(Icons.upload_file_rounded, color: p.accent),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Upload a file', style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              Text('CSV or Excel, up to 25 MB', style: t.bodySmall?.copyWith(color: p.muted)),
            ]),
          ),
        ]),
        const SizedBox(height: 14),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: busy ? null : onPick,
            icon: busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.2))
                : const Icon(Icons.add_rounded),
            label: Text(busy ? (stage ?? 'Reading your data...') : 'Choose file'),
          ),
        ),
        if (busy && progress != null) ...[
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(
              value: progress! >= 0.999 ? null : progress,
              minHeight: 8,
              backgroundColor: p.border,
              semanticsLabel: 'Upload progress',
            ),
          ),
          const SizedBox(height: 6),
          Text(
            progress! >= 0.999
                ? 'File sent. Cleaning and checking your data...'
                : 'Sending ${(progress! * 100).round()}% · keep the app open',
            style: t.bodySmall?.copyWith(color: p.muted),
          ),
        ],
        const SizedBox(height: 4),
        SizedBox(
          width: double.infinity,
          child: TextButton.icon(
            onPressed: busy ? null : onSample,
            icon: const Icon(Icons.storefront_rounded),
            label: const Text('Try with sample data'),
          ),
        ),
        if (error != null) ...[const SizedBox(height: 10), InlineError(error!)],
      ]),
    );
  }
}

class _SheetCard extends StatelessWidget {
  const _SheetCard({required this.busy, required this.onTap});

  final bool busy;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return AppCard(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        minTileHeight: kMinTouch,
        enabled: !busy,
        leading: Icon(Icons.grid_on_rounded, color: p.accent),
        title: Text(busy ? 'Reading your sheet...' : 'Import from Google Sheets'),
        subtitle: const Text('Paste a link shared with anyone'),
        trailing: Icon(Icons.chevron_right_rounded, color: p.muted),
        onTap: onTap,
      ),
    );
  }
}

class _SheetDialog extends StatefulWidget {
  const _SheetDialog();

  @override
  State<_SheetDialog> createState() => _SheetDialogState();
}

class _SheetDialogState extends State<_SheetDialog> {
  final _field = TextEditingController();

  @override
  void dispose() {
    _field.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Import from Google Sheets'),
        content: TextField(
          controller: _field,
          autofocus: true,
          keyboardType: TextInputType.url,
          autocorrect: false,
          decoration: const InputDecoration(
            hintText: 'https://docs.google.com/spreadsheets/...',
            helperText: "Set Share to 'Anyone with the link'",
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, _field.text.trim()), child: const Text('Import')),
        ],
      );
}

/// "Analyse as": sales data (business dashboard) or general data (EDA, Predict).
class _KindCard extends StatelessWidget {
  const _KindCard({
    required this.general,
    required this.salesSetup,
    required this.busy,
    required this.onGeneral,
    required this.onSales,
  });

  final bool general;
  final bool salesSetup;
  final bool busy;
  final VoidCallback onGeneral;
  final VoidCallback onSales;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final salesSelected = !general || salesSetup;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('Analyse as', style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 10),
        SegmentedButton<bool>(
          segments: const [
            ButtonSegment(value: true, icon: Icon(Icons.storefront_rounded), label: Text('Sales data')),
            ButtonSegment(value: false, icon: Icon(Icons.travel_explore_rounded), label: Text('General data')),
          ],
          selected: {salesSelected},
          showSelectedIcon: false,
          onSelectionChanged: busy
              ? null
              : (s) {
                  if (s.first == salesSelected) return;
                  if (s.first) {
                    onSales();
                  } else {
                    onGeneral();
                  }
                },
        ),
        const SizedBox(height: 10),
        Text(
          salesSelected
              ? 'Orders or transactions with a date and an amount: revenue dashboard, forecasts, '
                  'customers and monthly reports.'
              : 'Any table, like passengers, patients, students or survey answers: a full data '
                  'analysis, findings, Predict a column and Ask AI.',
          style: t.bodySmall?.copyWith(color: p.muted, height: 1.4),
        ),
      ]),
    );
  }
}

class _ProfileSection extends StatelessWidget {
  const _ProfileSection({
    required this.profile,
    required this.mapping,
    required this.dirty,
    required this.saving,
    required this.onAssign,
    required this.onBuild,
    required this.onDelete,
    required this.salesSetup,
    required this.onGeneral,
    required this.onSales,
  });

  final DatasetProfile profile;
  final Map<String, String?> mapping;
  final bool dirty;
  final bool saving;
  final void Function(String column, String? role) onAssign;
  final VoidCallback onBuild;
  final VoidCallback onDelete;
  final bool salesSetup;
  final VoidCallback onGeneral;
  final VoidCallback onSales;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final general = profile.dataset.isGeneral;
    final kind = _KindCard(
      general: general,
      salesSetup: salesSetup,
      busy: saving,
      onGeneral: onGeneral,
      onSales: onSales,
    );
    if (general && !salesSetup) {
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        kind,
        if (profile.quality != null) ...[
          const SizedBox(height: 20),
          const SectionTitle('Data quality'),
          _QualityCard(report: profile.quality!),
        ],
        const SizedBox(height: 20),
        FilledButton.icon(
          onPressed: saving ? null : onBuild,
          icon: const Icon(Icons.travel_explore_rounded),
          label: const Text('Explore this data'),
        ),
        const SizedBox(height: 6),
        TextButton.icon(
          onPressed: saving ? null : onDelete,
          style: TextButton.styleFrom(foregroundColor: p.negative),
          icon: const Icon(Icons.delete_outline_rounded),
          label: const Text('Delete this dataset'),
        ),
      ]);
    }
    final t = Theme.of(context).textTheme;
    final roleByColumn = {for (final e in mapping.entries) if (e.value != null) e.value!: e.key};
    final missing = profile.requiredRoles.where((r) => mapping[r] == null).toList();
    final byAi = profile.mappingSource == 'llm' && !dirty;

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      kind,
      const SizedBox(height: 16),
      SectionTitle(byAi ? 'AI mapped your columns' : 'Your columns',
          trailing: byAi ? Pill('AI', icon: Icons.auto_awesome) : null),
      Text('Tap a role to change it. Date and revenue are required.',
          style: t.bodySmall?.copyWith(color: p.muted)),
      const SizedBox(height: 10),
      AppCard(
        padding: EdgeInsets.zero,
        child: Column(children: [
          for (final (i, col) in profile.columns.indexed) ...[
            if (i > 0) const Divider(height: 1),
            _ColumnRow(
              column: col,
              role: roleByColumn[col.name],
              onTap: () => _chooseRole(context, col, roleByColumn[col.name]),
            ),
          ],
        ]),
      ),
      if (profile.quality != null && !dirty) ...[
        const SizedBox(height: 20),
        const SectionTitle('Data quality'),
        _QualityCard(report: profile.quality!),
      ],
      const SizedBox(height: 20),
      if (missing.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: InlineError('Choose a column for: ${missing.map((r) => roleLabels[r]).join(', ')}.'),
        ),
      FilledButton.icon(
        onPressed: missing.isEmpty && !saving ? onBuild : null,
        icon: saving
            ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.2))
            : const Icon(Icons.dashboard_customize_rounded),
        label: Text(dirty ? 'Save and build my dashboard' : 'Build my dashboard'),
      ),
      const SizedBox(height: 6),
      TextButton.icon(
        onPressed: saving ? null : onDelete,
        style: TextButton.styleFrom(foregroundColor: p.negative),
        icon: const Icon(Icons.delete_outline_rounded),
        label: const Text('Delete this dataset'),
      ),
    ]);
  }

  void _chooseRole(BuildContext context, ColumnInfo col, String? currentRole) {
    showModalBottomSheet<void>(
      useRootNavigator: true,
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheet) => SafeArea(
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text('"${col.name}" is...', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
            ),
            for (final role in profile.roles)
              ListTile(
                minTileHeight: kMinTouch,
                leading: Icon(role == currentRole ? Icons.check_circle : Icons.circle_outlined,
                    color: sheet.palette.accent),
                title: Text(roleLabels[role] ?? role),
                subtitle: Text(_roleHelp[role] ?? ''),
                onTap: () {
                  onAssign(col.name, role);
                  Navigator.pop(sheet);
                },
              ),
            ListTile(
              minTileHeight: kMinTouch,
              leading: Icon(currentRole == null ? Icons.check_circle : Icons.circle_outlined,
                  color: sheet.palette.muted),
              title: const Text('Not used'),
              onTap: () {
                onAssign(col.name, null);
                Navigator.pop(sheet);
              },
            ),
          ]),
        ),
      ),
    );
  }
}

class _ColumnRow extends StatelessWidget {
  const _ColumnRow({required this.column, required this.role, required this.onTap});

  final ColumnInfo column;
  final String? role;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final sample = column.samples.isEmpty ? '' : column.samples.first;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(column.name, style: t.bodyLarge?.copyWith(fontWeight: FontWeight.w600)),
              if (sample.isNotEmpty)
                Text('e.g. $sample', maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: t.bodySmall?.copyWith(color: p.muted)),
            ]),
          ),
          const SizedBox(width: 10),
          ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 36),
            child: role == null
                ? Pill('Not used', color: p.muted, background: p.border, icon: Icons.add)
                : Pill(roleLabels[role] ?? role!, icon: Icons.edit_outlined),
          ),
        ]),
      ),
    );
  }
}

class _QualityCard extends StatelessWidget {
  const _QualityCard({required this.report});

  final QualityReport report;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = Theme.of(context).textTheme;
    final color = report.score >= 75 ? p.positive : (report.score >= 50 ? p.forecast : p.negative);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Semantics(
            label: 'Data quality ${report.score} out of 100',
            excludeSemantics: true,
            child: RingGauge(
              value: report.score.toDouble(),
              color: color,
              size: 92,
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Text('${report.score}', style: t.headlineSmall?.copyWith(fontWeight: FontWeight.w800, height: 1)),
                Text('/ 100', style: t.labelSmall?.copyWith(color: p.muted)),
              ]),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Pill(report.label, color: color, background: color.withValues(alpha: 0.12)),
              const SizedBox(height: 8),
              Text(
                report.issues.isEmpty
                    ? 'No problems found. Your numbers can be trusted.'
                    : '${report.issues.length} thing${report.issues.length == 1 ? '' : 's'} worth knowing about this file.',
                style: t.bodyMedium?.copyWith(color: p.muted),
              ),
            ]),
          ),
        ]),
        if (report.issues.isNotEmpty) const SizedBox(height: 14),
        for (final issue in report.issues)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(
                switch (issue.severity) {
                  'critical' => Icons.error_rounded,
                  'warning' => Icons.warning_amber_rounded,
                  _ => Icons.info_outline_rounded,
                },
                size: 20,
                color: switch (issue.severity) {
                  'critical' => p.negative,
                  'warning' => p.forecast,
                  _ => p.muted,
                },
              ),
              const SizedBox(width: 10),
              Expanded(child: Text(issue.message, style: t.bodyMedium)),
            ]),
          ),
      ]),
    );
  }
}
