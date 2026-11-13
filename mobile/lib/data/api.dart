import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../core/api_client.dart';
import 'models.dart';

/// Every backend call the app makes. Mock this class in widget tests.
class InsightPulseApi {
  InsightPulseApi(this._http);

  final ApiClient _http;

  // ------------------------------------------------------------ auth
  Future<AuthResult> login(String email, String password) async =>
      AuthResult.fromJson(await _http.post('/auth/login', data: {'email': email, 'password': password}));

  /// Exchange a Firebase ID token from Google sign-in for our own access token.
  Future<AuthResult> loginWithFirebase(String idToken) async =>
      AuthResult.fromJson(await _http.post('/auth/firebase', data: {'id_token': idToken}));

  Future<AuthResult> register(String email, String password) async =>
      AuthResult.fromJson(await _http.post('/auth/register', data: {'email': email, 'password': password}));

  // ------------------------------------------------------------ datasets
  Future<List<DatasetSummary>> datasets() async =>
      ((await _http.get('/datasets')) as List).map((e) => DatasetSummary.fromJson(e as Map<String, dynamic>)).toList();

  Future<DatasetProfile> upload(Uint8List bytes, String filename, {void Function(double fraction)? onProgress}) async {
    final form = FormData.fromMap({'file': MultipartFile.fromBytes(bytes, filename: filename)});
    return DatasetProfile.fromJson(await _http.postFile(
      '/datasets',
      form,
      onProgress: onProgress == null ? null : (sent, total) => onProgress(total > 0 ? sent / total : 0),
    ));
  }

  Future<DatasetProfile> loadSample() async => DatasetProfile.fromJson(await _http.post('/datasets/sample'));

  Future<DatasetProfile> importSheet(String url) async =>
      DatasetProfile.fromJson(await _http.post('/datasets/import-sheet', data: {'url': url}));

  Future<void> deleteDataset(String datasetId) async {
    await _http.delete('/datasets/$datasetId');
  }

  Future<DatasetProfile> profile(String datasetId) async =>
      DatasetProfile.fromJson(await _http.get('/datasets/$datasetId/profile'));

  Future<DatasetProfile> saveMapping(String datasetId, Map<String, String?> mapping) async =>
      DatasetProfile.fromJson(await _http.put('/datasets/$datasetId/mapping', data: mapping));

  // ------------------------------------------------------------ insights
  Future<Dashboard> dashboard(String datasetId, String period) async =>
      Dashboard.fromJson(await _http.get('/datasets/$datasetId/dashboard', query: {'period': period}));

  Future<InsightFeed> insights(String datasetId, {String? category}) async =>
      InsightFeed.fromJson(await _http.get('/datasets/$datasetId/insights', query: {'category': ?category}));

  Future<List<Recommendation>> recommendations(String datasetId) async {
    final data = await _http.get('/datasets/$datasetId/recommendations') as Map;
    return ((data['actions'] as List?) ?? const [])
        .map((e) => Recommendation.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  // ------------------------------------------------------------ ML
  Future<Job> startForecast(String datasetId, String target, int horizonDays) async => Job.fromJson(
    await _http.post('/datasets/$datasetId/forecast', data: {'target': target, 'horizon_days': horizonDays}),
  );

  Future<Job> job(String jobId) async => Job.fromJson(await _http.get('/jobs/$jobId'));

  Future<WhatIfResult> whatIf(String datasetId, double changePct) async => WhatIfResult.fromJson(
    await _http.post('/datasets/$datasetId/whatif', data: {'lever': 'price', 'change_pct': changePct}),
  );

  Future<ChurnReport> churn(String datasetId) async =>
      ChurnReport.fromJson(await _http.post('/datasets/$datasetId/predict/churn'));

  Future<List<CustomerSegment>> segments(String datasetId) async {
    final j = await _http.get('/datasets/$datasetId/segments') as Map<String, dynamic>;
    return [for (final s in j['segments'] as List) CustomerSegment.fromJson(s as Map<String, dynamic>)];
  }

  // ------------------------------------------------------------ general data
  Future<Exploration> explore(String datasetId, {String? target}) async => Exploration.fromJson(
        await _http.get('/datasets/$datasetId/explore', query: {'target': ?target}) as Map<String, dynamic>,
      );

  Future<Prediction> predict(String datasetId, String target) async => Prediction.fromJson(
        await _http.post('/datasets/$datasetId/predict', data: {'target': target}) as Map<String, dynamic>,
      );

  /// Analyse the dataset as 'sales' or 'general' data.
  Future<DatasetSummary> setKind(String datasetId, String kind) async => DatasetSummary.fromJson(
        await _http.put('/datasets/$datasetId/kind', data: {'kind': kind}) as Map<String, dynamic>,
      );

  /// The data report PDF of a general dataset.
  Future<Uint8List> dataReport(String datasetId) => _http.getBytes('/datasets/$datasetId/report');

  // ------------------------------------------------------------ reports
  Future<ReportMonths> reportMonths(String datasetId) async =>
      ReportMonths.fromJson(await _http.get('/datasets/$datasetId/report/months') as Map<String, dynamic>);

  /// The monthly PDF report as bytes.
  Future<Uint8List> monthlyReport(String datasetId, String month) =>
      _http.getBytes('/datasets/$datasetId/report', query: {'month': month});

  // ------------------------------------------------------------ AI
  Future<ChatReply> chat(String datasetId, String message, List<Map<String, String>> history) async =>
      ChatReply.fromJson(await _http.post('/datasets/$datasetId/chat', data: {'message': message, 'history': history}));

  // ------------------------------------------------------------ charts
  Future<Uint8List> chartPng(String url, {required bool dark}) =>
      _http.getBytes(url, query: {'theme': dark ? 'dark' : 'light'});
}
