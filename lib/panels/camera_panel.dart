import 'package:flutter/material.dart';
import 'package:flutter_mjpeg/flutter_mjpeg.dart';
import '../services/backend_service.dart';

class CameraPanel extends StatefulWidget {
  final List<Map<String, dynamic>> scanData;
  final String currentScanId; // <-- NEW
  final Function(String imagePath, String side, String view, Map<String, String> aiResult) onImageCaptured;
  final VoidCallback onReset;

  const CameraPanel({
<<<<<<< Updated upstream
    super.key,
    required this.cameras,
    required this.scanData,
    required this.onImageCaptured,
    required this.onReset,
=======
    super.key, 
    required this.scanData, 
    required this.currentScanId, // <-- NEW 
    required this.onImageCaptured, 
    required this.onReset
>>>>>>> Stashed changes
  });

  @override
  State<CameraPanel> createState() => _CameraPanelState();
}

class _CameraPanelState extends State<CameraPanel> {
<<<<<<< Updated upstream
  CameraController? _controller;
  bool _isCapturing = false;
  bool _hasNoCamera = false;

  bool _isConfigured = false;
=======
>>>>>>> Stashed changes
  String? _selectedSide;
  String? _selectedView;
  bool _isProcessing = false;

  void _executeCapture() async {
    if (_selectedSide == null || _selectedView == null) return;
    setState(() => _isProcessing = true);

<<<<<<< Updated upstream
  @override
  void didUpdateWidget(CameraPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.scanData.isEmpty && oldWidget.scanData.isNotEmpty) {
      _isConfigured = false;
    }
  }

  Future<void> _initializeCamera(int index) async {
    if (widget.cameras.isEmpty) {
      if (mounted) setState(() => _hasNoCamera = true);
      return;
    }
    await _controller?.dispose();
    _controller = CameraController(
      widget.cameras[index],
      ResolutionPreset.medium,
      enableAudio: false,
    );

=======
>>>>>>> Stashed changes
    try {
      final result = await BackendService.triggerPythonCapture(
        scanId: widget.currentScanId, // <-- NEW: Sent to backend service
        side: _selectedSide!, 
        view: _selectedView!
      );

      final aiData = {
        'classification': result['classification'].toString(),
        'confidence': result['confidence'].toString(),
        'recommendation': result['recommendation'].toString(),
      };

      widget.onImageCaptured(result['image_path'].toString(), _selectedSide!, _selectedView!, aiData);
      setState(() { _selectedSide = null; _selectedView = null; });
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to connect to AI server', style: TextStyle(color: Colors.white)), backgroundColor: Colors.red));
    } finally {
      if (mounted) setState(() => _isProcessing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
<<<<<<< Updated upstream
    String? takenSide = widget.scanData.isNotEmpty
        ? widget.scanData[0]['side']
        : null;

    // The Configuration Picker Phase
    if (!_isConfigured) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Card(
                elevation: 2,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(20.0),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        'Configure Scan #${widget.scanData.length + 1} of 2',
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF0F172A),
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 20),
                      const Text(
                        'Select Breast Side:',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF475569),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: ChoiceChip(
                              label: const Center(child: Text('Left Breast')),
                              selected: _selectedSide == 'Left',
                              onSelected: takenSide == 'Left'
                                  ? null
                                  : (val) =>
                                        setState(() => _selectedSide = 'Left'),
                              selectedColor: const Color(0xFF0D9488),
                              labelStyle: TextStyle(
                                color: _selectedSide == 'Left'
                                    ? Colors.white
                                    : (takenSide == 'Left'
                                          ? Colors.grey
                                          : Colors.black),
                              ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: ChoiceChip(
                              label: const Center(child: Text('Right Breast')),
                              selected: _selectedSide == 'Right',
                              onSelected: takenSide == 'Right'
                                  ? null
                                  : (val) =>
                                        setState(() => _selectedSide = 'Right'),
                              selectedColor: const Color(0xFF0D9488),
                              labelStyle: TextStyle(
                                color: _selectedSide == 'Right'
                                    ? Colors.white
                                    : (takenSide == 'Right'
                                          ? Colors.grey
                                          : Colors.black),
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 20),
                      const Text(
                        'Select View:',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF475569),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: ChoiceChip(
                              label: const Center(child: Text('CC')),
                              selected: _selectedView == 'CC',
                              onSelected: (val) =>
                                  setState(() => _selectedView = 'CC'),
                              selectedColor: const Color(0xFF0D9488),
                              labelStyle: TextStyle(
                                color: _selectedView == 'CC'
                                    ? Colors.white
                                    : Colors.black,
                              ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: ChoiceChip(
                              label: const Center(child: Text('MLO')),
                              selected: _selectedView == 'MLO',
                              onSelected: (val) =>
                                  setState(() => _selectedView = 'MLO'),
                              selectedColor: const Color(0xFF0D9488),
                              labelStyle: TextStyle(
                                color: _selectedView == 'MLO'
                                    ? Colors.white
                                    : Colors.black,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 32),
                      ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF0D9488),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                        onPressed:
                            (_selectedSide != null && _selectedView != null)
                            ? () => setState(() => _isConfigured = true)
                            : null,
                        child: const Text(
                          'Proceed to Camera',
                          style: TextStyle(color: Colors.white, fontSize: 16),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              // Reset Current Scans Button
              if (widget.scanData.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 16.0),
                  child: TextButton.icon(
                    icon: const Icon(Icons.refresh, color: Colors.redAccent),
                    label: const Text(
                      'Discard Capture & Reset',
                      style: TextStyle(
                        color: Colors.redAccent,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    onPressed: widget.onReset,
                  ),
                ),
            ],
          ),
        ),
      );
    }

    // Mock Camera Mode (If no webcam is attached)
    if (_hasNoCamera ||
        _controller == null ||
        !_controller!.value.isInitialized) {
      return Container(
        color: Colors.black,
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.videocam_off, color: Colors.white54, size: 64),
              const SizedBox(height: 16),
              const Text(
                'Mock Camera Mode',
                style: TextStyle(color: Colors.white, fontSize: 16),
              ),
              const SizedBox(height: 20),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF475569),
                ),
                onPressed: () {
                  widget.onImageCaptured(
                    XFile(''),
                    _selectedSide!,
                    _selectedView!,
                  );
                  _cancelConfig(); // Properly forces UI back to the picking phase
                },
                child: Text(
                  'Simulate ${_selectedSide} ($_selectedView)',
                  style: const TextStyle(color: Colors.white),
                ),
              ),
              const SizedBox(height: 16),
              TextButton(
                onPressed: _cancelConfig,
                child: const Text(
                  'Cancel & Go Back',
                  style: TextStyle(color: Colors.redAccent),
                ),
              ),
            ],
          ),
        ),
      );
    }

    // Live Camera Mode
    return Stack(
      children: [
        SizedBox(
          width: double.infinity,
          height: double.infinity,
          child: CameraPreview(_controller!),
        ),

        // Target HUD
        Positioned(
          top: 16,
          left: 16,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            color: Colors.black54,
            child: Text(
              'Target: $_selectedSide Breast ($_selectedView)',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ),

        // Camera Switcher
        if (widget.cameras.length > 1)
          Positioned(
            top: 16,
            right: 72,
            child: FloatingActionButton(
              mini: true,
              backgroundColor: Colors.black54,
              elevation: 0,
              onPressed: () {
                setState(() => _controller = null);
                _selectedCameraIndex =
                    (_selectedCameraIndex + 1) % widget.cameras.length;
                _initializeCamera(_selectedCameraIndex);
              },
              child: const Icon(Icons.cameraswitch, color: Colors.white),
            ),
          ),

        // Cancel/Back Button
        Positioned(
          top: 16,
          right: 16,
          child: FloatingActionButton(
            mini: true,
            backgroundColor: Colors.redAccent.withOpacity(0.8),
            elevation: 0,
            onPressed: _cancelConfig, // Allows user to return to picking phase without capturing
            child: const Icon(Icons.close, color: Colors.white),
          ),
        ),

        // Shutter Button
        Align(
          alignment: Alignment.bottomCenter,
          child: Padding(
            padding: const EdgeInsets.only(bottom: 30),
            child: Material(
              color: Colors.transparent,
              child: InkWell(
                borderRadius: BorderRadius.circular(40),
                onTap: _isCapturing
                    ? null
                    : () async {
                        setState(() => _isCapturing = true);
                        try {
                          final image = await _controller!.takePicture();
                          widget.onImageCaptured(
                            image,
                            _selectedSide!,
                            _selectedView!,
                          );
                          _cancelConfig(); // Resets back to config for the next shot
                        } catch (e) {
                          debugPrint('Error: $e');
                        } finally {
                          if (mounted) setState(() => _isCapturing = false);
                        }
                      },
                child: Container(
                  width: 80,
                  height: 80,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: const Color(0xFF0D9488),
                      width: 6,
                    ),
                    color: const Color(0xFF14B8A6),
                  ),
=======
    return Column( // CHANGED TO COLUMN FOR PORTRAIT
      children: [
        // Top Half: Camera Stream
        Expanded(
          flex: 5,
          child: Container(
            color: Colors.black,
            child: Stack(
              fit: StackFit.expand,
              children: [
                Mjpeg(
                  isLive: true,
                  stream: 'http://127.0.0.1:5000/stream',
                  error: (context, error, stack) => const Center(child: Text('Connecting to Python Camera...', style: TextStyle(color: Colors.white54))),
                ),
                if (_isProcessing)
                  Container(
                    color: Colors.black87,
                    child: const Center(child: Column(mainAxisSize: MainAxisSize.min, children: [CircularProgressIndicator(color: Color(0xFF0D9488)), SizedBox(height: 16), Text('Processing Inference...', style: TextStyle(color: Colors.white, fontSize: 16))])),
                  ),
              ],
            ),
          ),
        ),
        // Bottom Half: Controls
        Expanded(
          flex: 5,
          child: Container(
            color: const Color(0xFF0F172A),
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('SCAN CONFIG', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18)),
                const SizedBox(height: 12),
                Row(
                  children: ['Left', 'Right'].map((side) => Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4.0),
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _selectedSide == side ? const Color(0xFF0D9488) : const Color(0xFF334155), padding: const EdgeInsets.symmetric(vertical: 20)),
                        onPressed: () => setState(() => _selectedSide = side),
                        child: Text(side, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                      ),
                    ),
                  )).toList(),
>>>>>>> Stashed changes
                ),
                const SizedBox(height: 12),
                Row(
                  children: ['CC', 'MLO'].map((view) => Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4.0),
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _selectedView == view ? const Color(0xFF0D9488) : const Color(0xFF334155), padding: const EdgeInsets.symmetric(vertical: 20)),
                        onPressed: () => setState(() => _selectedView = view),
                        child: Text(view, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                      ),
                    ),
                  )).toList(),
                ),
                const Spacer(),
                ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0D9488), padding: const EdgeInsets.symmetric(vertical: 20)),
                  onPressed: (_selectedSide != null && _selectedView != null && !_isProcessing) ? _executeCapture : null,
                  icon: const Icon(Icons.camera, color: Colors.white, size: 28),
                  label: const Text('CAPTURE', style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
