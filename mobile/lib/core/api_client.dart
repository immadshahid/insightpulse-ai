import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'config.dart';

/// A failed API call, with a message that is safe to show to the user.
class ApiException implements Exception {
  ApiException(this.message, {this.status});

  final String message;
  final int? status;

  bool get isUnauthorized => status == 401;
  bool get isUnavailable => status == 503;

  @override
  String toString() => message;
}

/// Where the access token lives (secure storage on device, memory in tests).
abstract class TokenStore {
  String? get token;
  String? get email;
  Future<void> load();
  Future<void> save(String token, String email);
  Future<void> clear();
}

class SecureTokenStore implements TokenStore {
  SecureTokenStore([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  String? _token;
  String? _email;

  @override
  String? get token => _token;

  @override
  String? get email => _email;

  @override
  Future<void> load() async {
    _token = await _storage.read(key: 'access_token');
    _email = await _storage.read(key: 'email');
  }

  @override
  Future<void> save(String token, String email) async {
    _token = token;
    _email = email;
    await _storage.write(key: 'access_token', value: token);
    await _storage.write(key: 'email', value: email);
  }

  @override
  Future<void> clear() async {
    _token = null;
    _email = null;
    await _storage.delete(key: 'access_token');
    await _storage.delete(key: 'email');
  }
}

class MemoryTokenStore implements TokenStore {
  // ignore: prefer_initializing_formals
  MemoryTokenStore({String? token, String? email}) : _token = token, _email = email;

  String? _token;
  String? _email;

  @override
  String? get token => _token;

  @override
  String? get email => _email;

  @override
  Future<void> load() async {}

  @override
  Future<void> save(String token, String email) async {
    _token = token;
    _email = email;
  }

  @override
  Future<void> clear() async {
    _token = null;
    _email = null;
  }
}

/// Thin HTTP wrapper: adds the bearer token, maps errors to [ApiException].
class ApiClient {
  ApiClient(this._tokens, {Dio? dio, this.onUnauthorized})
      : _dio = dio ??
            Dio(BaseOptions(
              baseUrl: AppConfig.apiRoot,
              connectTimeout: const Duration(seconds: 15),
              receiveTimeout: const Duration(seconds: 180),
            )) {
    _dio.interceptors.add(InterceptorsWrapper(onRequest: (options, handler) {
      final token = _tokens.token;
      if (token != null) options.headers['Authorization'] = 'Bearer $token';
      handler.next(options);
    }));
  }

  final Dio _dio;
  final TokenStore _tokens;
  void Function()? onUnauthorized;

  /// Sends every later request to [serverUrl] (no trailing slash).
  void useServer(String serverUrl) => _dio.options.baseUrl = '$serverUrl/api/v1';

  /// True if an InsightPulse server answers at [serverUrl].
  Future<bool> canReach(String serverUrl) async {
    try {
      final r = await Dio(BaseOptions(connectTimeout: const Duration(seconds: 5), receiveTimeout: const Duration(seconds: 5)))
          .get<dynamic>('$serverUrl/health');
      return r.statusCode == 200;
    } on DioException {
      return false;
    }
  }

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _send(() => _dio.get<dynamic>(path, queryParameters: query));

  Future<dynamic> delete(String path) => _send(() => _dio.delete<dynamic>(path));

  Future<dynamic> post(String path, {Object? data}) =>
      _send(() => _dio.post<dynamic>(path, data: data));

  Future<dynamic> put(String path, {Object? data}) =>
      _send(() => _dio.put<dynamic>(path, data: data));

  /// Raw bytes (chart PNGs). [path] may include the `/api/v1` prefix.
  Future<Uint8List> getBytes(String path, {Map<String, dynamic>? query}) async {
    final relative = path.startsWith('/api/v1') ? path.substring(7) : path;
    final data = await _send(() => _dio.get<List<int>>(
          relative,
          queryParameters: query,
          options: Options(responseType: ResponseType.bytes),
        ));
    return Uint8List.fromList(data as List<int>);
  }

  Future<dynamic> _send(Future<Response<dynamic>> Function() call) async {
    try {
      final response = await call();
      return response.data;
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status == 401 && _tokens.token != null) onUnauthorized?.call();
      throw ApiException(_message(e), status: status);
    }
  }

  static String _message(DioException e) {
    final data = e.response?.data;
    if (data is Map && data['detail'] != null) {
      final detail = data['detail'];
      if (detail is String) return detail;
      if (detail is List && detail.isNotEmpty) {
        final first = detail.first;
        if (first is Map && first['msg'] != null) {
          final field = (first['loc'] as List?)?.last;
          return field == null ? '${first['msg']}' : '$field: ${first['msg']}';
        }
      }
    }
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.sendTimeout:
        return 'The server took too long to respond. Please try again.';
      case DioExceptionType.connectionError:
        return "Can't reach the InsightPulse server. Check your connection.";
      default:
        return 'Something went wrong (${e.response?.statusCode ?? 'network'}).';
    }
  }
}
