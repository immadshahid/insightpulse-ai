import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/core/api_client.dart';

/// Fails every request with the given network error.
class _Failing implements HttpClientAdapter {
  _Failing(this.type);
  final DioExceptionType type;

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<List<int>>? requestStream, Future<void>? cancelFuture) =>
      throw DioException(requestOptions: options, type: type);

  @override
  void close({bool force = false}) {}
}

Future<String> messageFor(DioExceptionType type) async {
  final client = ApiClient(MemoryTokenStore(), dio: Dio()..httpClientAdapter = _Failing(type));
  try {
    await client.postFile('/datasets', FormData());
  } on ApiException catch (e) {
    return e.message;
  }
  return 'no error';
}

void main() {
  test('each kind of time-out says which stage failed', () async {
    expect(await messageFor(DioExceptionType.connectionTimeout), contains('same Wi-Fi'));
    expect(await messageFor(DioExceptionType.sendTimeout), startsWith('Sending took too long'));
    expect(await messageFor(DioExceptionType.receiveTimeout), contains('took too long to respond'));
    expect(await messageFor(DioExceptionType.connectionError), contains("Can't reach"));
  });
}
