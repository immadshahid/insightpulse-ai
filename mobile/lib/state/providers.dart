import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_client.dart';
import '../core/google_auth.dart';
import '../core/prefs.dart';
import '../data/api.dart';
import '../data/models.dart';

// ---------------------------------------------------------------- infrastructure
/// Overridden in main() (secure storage) and in tests (memory).
final tokenStoreProvider = Provider<TokenStore>((ref) => MemoryTokenStore());

/// Overridden in main() (shared preferences) and in tests (memory).
final prefsProvider = Provider<Prefs>((ref) => MemoryPrefs());

/// Overridden in main() with Firebase when the app was built with Firebase settings.
final googleAuthProvider = Provider<GoogleAuth>((ref) => const GoogleAuthUnavailable());

final apiClientProvider = Provider<ApiClient>((ref) {
  final client = ApiClient(ref.watch(tokenStoreProvider));
  client.onUnauthorized = () => ref.read(authProvider.notifier).logout();
  final saved = ref.watch(prefsProvider).getString(PrefKeys.serverUrl);
  if (saved != null) client.useServer(saved);
  return client;
});

/// Turns what the user typed ("192.168.1.5", "http://x:8000/") into a server address.
String normalizeServerUrl(String input) {
  var url = input.trim().replaceAll(RegExp(r'/+$'), '');
  if (url.isEmpty) return url;
  if (!url.contains('://')) url = 'http://$url';
  final hasPort = Uri.tryParse(url)?.hasPort ?? false;
  return !hasPort && url.startsWith('http://') ? '$url:8000' : url;
}

final apiProvider = Provider<InsightPulseApi>((ref) => InsightPulseApi(ref.watch(apiClientProvider)));

// ---------------------------------------------------------------- auth
class Session {
  const Session(this.email);
  final String email;

  String get firstName {
    final local = email.split('@').first.split(RegExp(r'[._-]')).first;
    return local.isEmpty ? 'there' : local[0].toUpperCase() + local.substring(1);
  }
}

class AuthController extends Notifier<Session?> {
  @override
  Session? build() {
    final store = ref.watch(tokenStoreProvider);
    return store.token != null ? Session(store.email ?? '') : null;
  }

  Future<void> login(String email, String password) async =>
      _finish(await ref.read(apiProvider).login(email.trim(), password));

  Future<void> register(String email, String password) async =>
      _finish(await ref.read(apiProvider).register(email.trim(), password));

  /// Google sign-in; false if the user backed out of the account chooser.
  Future<bool> loginWithGoogle() async {
    final idToken = await ref.read(googleAuthProvider).signIn();
    if (idToken == null) return false;
    await _finish(await ref.read(apiProvider).loginWithFirebase(idToken));
    return true;
  }

  Future<void> _finish(AuthResult r) async {
    await ref.read(tokenStoreProvider).save(r.token, r.email);
    state = Session(r.email);
  }

  Future<void> logout() async {
    try {
      await ref.read(googleAuthProvider).signOut();
    } catch (_) {
      // Signing out of Google is best effort; the app session ends regardless.
    }
    await ref.read(tokenStoreProvider).clear();
    ref.read(selectedDatasetIdProvider.notifier).select(null);
    state = null;
  }
}

final authProvider = NotifierProvider<AuthController, Session?>(AuthController.new);

// ---------------------------------------------------------------- preferences
class ThemeModeController extends Notifier<ThemeMode> {
  @override
  ThemeMode build() =>
      ThemeMode.values.asNameMap()[ref.watch(prefsProvider).getString(PrefKeys.themeMode)] ?? ThemeMode.system;

  void set(ThemeMode mode) {
    state = mode;
    ref.read(prefsProvider).setString(PrefKeys.themeMode, mode.name);
  }
}

final themeModeProvider = NotifierProvider<ThemeModeController, ThemeMode>(ThemeModeController.new);

const validPeriods = {'7d', '30d', '90d', '1y'};

class PeriodController extends Notifier<String> {
  @override
  String build() {
    final saved = ref.watch(prefsProvider).getString(PrefKeys.period);
    return validPeriods.contains(saved) ? saved! : '30d';
  }

  void set(String period) {
    state = period;
    ref.read(prefsProvider).setString(PrefKeys.period, period);
  }
}

final periodProvider = NotifierProvider<PeriodController, String>(PeriodController.new);

// ---------------------------------------------------------------- datasets
final datasetsProvider = FutureProvider<List<DatasetSummary>>((ref) async {
  if (ref.watch(authProvider) == null) return const [];
  return ref.watch(apiProvider).datasets();
});

class SelectedDatasetController extends Notifier<String?> {
  @override
  String? build() => ref.watch(prefsProvider).getString(PrefKeys.datasetId);

  void select(String? id) {
    state = id;
    final prefs = ref.read(prefsProvider);
    id == null ? prefs.remove(PrefKeys.datasetId) : prefs.setString(PrefKeys.datasetId, id);
  }
}

final selectedDatasetIdProvider = NotifierProvider<SelectedDatasetController, String?>(SelectedDatasetController.new);

/// The dataset the screens show: the user's choice, else the newest ready one.
final currentDatasetProvider = Provider<DatasetSummary?>((ref) {
  final list = ref.watch(datasetsProvider).value ?? const [];
  final chosen = ref.watch(selectedDatasetIdProvider);
  for (final d in list) {
    if (d.id == chosen) return d;
  }
  for (final d in list) {
    if (d.isReady) return d;
  }
  return list.isEmpty ? null : list.first;
});

final profileProvider = FutureProvider.autoDispose.family<DatasetProfile, String>(
  (ref, id) => ref.watch(apiProvider).profile(id),
);

/// Re-fetch every [every] while [pending] is true (background jobs still running).
void _pollWhile(Ref ref, bool pending, {Duration every = const Duration(seconds: 3)}) {
  if (!pending) return;
  final timer = Timer(every, ref.invalidateSelf);
  ref.onDispose(timer.cancel);
}

// ---------------------------------------------------------------- dashboard & insights
typedef DashboardKey = ({String datasetId, String period});

final dashboardProvider = FutureProvider.autoDispose.family<Dashboard, DashboardKey>((ref, key) async {
  final d = await ref.watch(apiProvider).dashboard(key.datasetId, key.period);
  _pollWhile(ref, d.isPending);
  return d;
});

typedef InsightsKey = ({String datasetId, String? category});

final insightsProvider = FutureProvider.autoDispose.family<InsightFeed, InsightsKey>((ref, key) async {
  final feed = await ref.watch(apiProvider).insights(key.datasetId, category: key.category);
  _pollWhile(ref, feed.isPending, every: const Duration(seconds: 4));
  return feed;
});

final recommendationsProvider = FutureProvider.autoDispose.family<List<Recommendation>, String>(
  (ref, id) => ref.watch(apiProvider).recommendations(id),
);

// ---------------------------------------------------------------- forecast
typedef ForecastKey = ({String datasetId, String target, int horizonDays});

/// Starts (or reuses) the forecast job and polls it until it finishes.
final forecastProvider = FutureProvider.autoDispose.family<ForecastResult, ForecastKey>((ref, key) async {
  final api = ref.watch(apiProvider);
  var job = await api.startForecast(key.datasetId, key.target, key.horizonDays);
  final deadline = DateTime.now().add(const Duration(minutes: 3));
  while (!job.isDone) {
    if (!ref.mounted || DateTime.now().isAfter(deadline)) {
      throw ApiException('The forecast is taking longer than usual. Pull to refresh.');
    }
    await Future<void>.delayed(const Duration(seconds: 2));
    job = await api.job(job.id);
  }
  if (job.status == 'failed') throw ApiException(job.error ?? 'The forecast failed.');
  return ForecastResult.fromJson(job.result!);
});

typedef WhatIfKey = ({String datasetId, int changePct});

final whatIfProvider = FutureProvider.autoDispose.family<WhatIfResult, WhatIfKey>(
  (ref, key) => ref.watch(apiProvider).whatIf(key.datasetId, key.changePct.toDouble()),
);

// ---------------------------------------------------------------- charts
typedef ChartKey = ({String url, bool dark});

/// Chart PNG bytes (fetched with the auth header; kept while the app runs).
final chartBytesProvider = FutureProvider.family<Uint8List, ChartKey>(
  (ref, key) => ref.watch(apiProvider).chartPng(key.url, dark: key.dark),
);

final reportMonthsProvider = FutureProvider.autoDispose.family<ReportMonths, String>(
  (ref, id) => ref.watch(apiProvider).reportMonths(id),
);

final churnProvider =FutureProvider.family<ChurnReport, String>((ref, id) => ref.watch(apiProvider).churn(id));

final segmentsProvider = FutureProvider.family<List<CustomerSegment>, String>(
  (ref, id) => ref.watch(apiProvider).segments(id),
);

/// Revenue goal per dashboard period, kept on this device.
class GoalsController extends Notifier<Map<String, double>> {
  @override
  Map<String, double> build() {
    final prefs = ref.watch(prefsProvider);
    return {for (final p in validPeriods) p: ?double.tryParse(prefs.getString(PrefKeys.goal(p)) ?? '')};
  }

  void set(String period, double? goal) {
    final prefs = ref.read(prefsProvider);
    if (goal == null) {
      prefs.remove(PrefKeys.goal(period));
      state = {...state}..remove(period);
    } else {
      prefs.setString(PrefKeys.goal(period), '$goal');
      state = {...state, period: goal};
    }
  }
}

final goalsProvider = NotifierProvider<GoalsController, Map<String, double>>(GoalsController.new);

// ---------------------------------------------------------------- Ask AI
class ChatEntry {
  const ChatEntry.user(this.text) : fromUser = true, reply = null, error = null, pending = false;
  const ChatEntry.ai(this.reply) : fromUser = false, text = '', error = null, pending = false;
  const ChatEntry.pending() : fromUser = false, text = '', reply = null, error = null, pending = true;
  const ChatEntry.error(this.error) : fromUser = false, text = '', reply = null, pending = false;

  final bool fromUser;
  final String text;
  final ChatReply? reply;
  final String? error;
  final bool pending;
}

class ChatController extends Notifier<List<ChatEntry>> {
  @override
  List<ChatEntry> build() {
    ref.watch(currentDatasetProvider.select((d) => d?.id)); // new dataset = new chat
    return const [];
  }

  bool get busy => state.isNotEmpty && state.last.pending;

  Future<void> send(String text) async {
    final message = text.trim();
    final dataset = ref.read(currentDatasetProvider);
    if (message.isEmpty || busy || dataset == null) return;
    final history = [
      for (final e in state)
        if (e.fromUser)
          {'role': 'user', 'content': e.text}
        else if (e.reply != null)
          {'role': 'assistant', 'content': e.reply!.answer},
    ];
    state = [...state, ChatEntry.user(message), const ChatEntry.pending()];
    try {
      final reply = await ref.read(apiProvider).chat(dataset.id, message, history);
      if (!ref.mounted) return;
      state = [...state.sublist(0, state.length - 1), ChatEntry.ai(reply)];
    } on ApiException catch (e) {
      if (!ref.mounted) return;
      final msg = e.isUnavailable
          ? 'Ask AI is not switched on for this server yet. An administrator needs to add '
                'an AI key (ANTHROPIC_API_KEY).'
          : e.message;
      state = [...state.sublist(0, state.length - 1), ChatEntry.error(msg)];
    }
  }

  void clear() => state = const [];
}

final chatProvider = NotifierProvider<ChatController, List<ChatEntry>>(ChatController.new);

/// A question another screen wants to hand to Ask AI (e.g. "Ask AI about this").
class ChatDraftController extends Notifier<String?> {
  @override
  String? build() => null;

  void set(String? text) => state = text;
}

final chatDraftProvider = NotifierProvider<ChatDraftController, String?>(ChatDraftController.new);
